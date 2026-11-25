import datetime
import io
import logging
import re
from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import ormcache
from odoo.tools.mail import html2plaintext

from .transport_trip import PRICING_METHODS

try:
    import openpyxl
except ImportError:  # pragma: no cover - openpyxl is an Odoo core dependency, always present
    openpyxl = None

_logger = logging.getLogger(__name__)

# A VIN/şasi no is 17 characters, letters (excluding I, O, Q) and digits.
CHASSIS_RE = re.compile(r'\b[A-HJ-NPR-Z0-9]{17}\b')

# Python'un varsayılan .lower()/.upper()/.title()'ı Türkçe İ/I/ı/i harflerini yanlış çeviriyor
# (örn. 'Ereğli'.upper() -> 'EREĞLI' olur, sondaki 'İ' yerine ASCII 'I' gelir - bu da referans
# tablosundaki doğru yazılmış 'EREĞLİ' ile eşleşmeyi sessizce bozar). Bu yüzden hem büyütme hem
# küçültme için Türkçe'ye özel, doğru çeviri yapan küçük yardımcılar kullanılıyor - gelen mail
# metni de, karşılaştırılan referans isimleri de (aşağıdaki il listesi dahil) TUTARLI şekilde bu
# fonksiyonlardan geçiriliyor; biri plain .upper(), diğeri _tr_upper() kullanırsa eşleşme sessizce
# bozulur.
_TR_UPPER_TO_LOWER_SPECIAL = {'İ': 'i', 'I': 'ı'}
_TR_LOWER_TO_UPPER_SPECIAL = {'i': 'İ', 'ı': 'I'}


def _tr_lower(text):
    return ''.join(_TR_UPPER_TO_LOWER_SPECIAL.get(ch, ch.lower()) for ch in text)


def _tr_upper(text):
    return ''.join(_TR_LOWER_TO_UPPER_SPECIAL.get(ch, ch.upper()) for ch in text)


def _tr_title(text):
    words = []
    for word in text.split(' '):
        if not word:
            words.append(word)
            continue
        lowered = _tr_lower(word)
        first = lowered[0]
        first_upper = 'İ' if first == 'i' else ('I' if first == 'ı' else first.upper())
        words.append(first_upper + lowered[1:])
    return ' '.join(words)


# Türkiye'nin 81 ili - gelen mailde bir şasi numarasıyla aynı satırda bu isimlerden biri
# geçiyorsa, o satırın alım/varış yeri olarak otomatik yakalanır. İlçe seviyesi için
# transport.address.lookup referans tablosu (data/transport_address_lookup.csv, PTT il/ilçe/
# mahalle listesinden) kullanılır - orada aynı il'e ait bir ilçe adı da yakınında geçiyorsa daha
# spesifik "İl / İlçe" şeklinde yakalanır. Mahalle seviyesi (73 bin satır) serbest metinde çok
# belirsiz/gürültülü olacağı için kasıtlı olarak eşleştirmeye dahil edilmiyor.
TURKISH_PROVINCES = [
    'Adana', 'Adıyaman', 'Afyonkarahisar', 'Ağrı', 'Aksaray', 'Amasya', 'Ankara', 'Antalya',
    'Ardahan', 'Artvin', 'Aydın', 'Balıkesir', 'Bartın', 'Batman', 'Bayburt', 'Bilecik',
    'Bingöl', 'Bitlis', 'Bolu', 'Burdur', 'Bursa', 'Çanakkale', 'Çankırı', 'Çorum', 'Denizli',
    'Diyarbakır', 'Düzce', 'Edirne', 'Elazığ', 'Erzincan', 'Erzurum', 'Eskişehir', 'Gaziantep',
    'Giresun', 'Gümüşhane', 'Hakkari', 'Hatay', 'Iğdır', 'Isparta', 'İstanbul', 'İzmir',
    'Kahramanmaraş', 'Karabük', 'Karaman', 'Kars', 'Kastamonu', 'Kayseri', 'Kırıkkale',
    'Kırklareli', 'Kırşehir', 'Kilis', 'Kocaeli', 'Konya', 'Kütahya', 'Malatya', 'Manisa',
    'Mardin', 'Mersin', 'Muğla', 'Muş', 'Nevşehir', 'Niğde', 'Ordu', 'Osmaniye', 'Rize',
    'Sakarya', 'Samsun', 'Siirt', 'Sinop', 'Sivas', 'Şanlıurfa', 'Şırnak', 'Tekirdağ', 'Tokat',
    'Trabzon', 'Tunceli', 'Uşak', 'Van', 'Yalova', 'Yozgat', 'Zonguldak',
]
# Mail metni _tr_upper() ile büyütülerek taranıyor; aynı dönüşümü burada da yaparak
# karşılaştırmayı tutarlı kılıyoruz (plain .upper() kullanılsaydı, örn. 'Kayseri'.upper() ASCII
# 'I' ile biten 'KAYSERI' verirdi ve mail metnindeki doğru 'KAYSERİ' ile hiç eşleşmezdi).
_PROVINCE_BY_UPPER = {_tr_upper(name): name for name in TURKISH_PROVINCES}
# Tüm illeri TEK bir regex taramasında yakalamak için (73 bin satırlık referans tablosuna rağmen
# mail başına performansı makul tutmak amacıyla), en uzun isimden en kısaya sıralanmış alternatif
# bir desen önceden derleniyor.
_PROVINCE_RE = re.compile(
    r'\b(%s)\b' % '|'.join(re.escape(p) for p in sorted(_PROVINCE_BY_UPPER, key=len, reverse=True))
)

# Satırda bir yer adının hemen öncesinde geçtiğinde, o yerin "alım yeri" mi yoksa "varış yeri" mi
# olduğunu belirlemekte kullanılan anahtar kelimeler (yanlış anlaşılmaya en az açık, net ifadeler
# seçildi - örn. tek başına "teslim" hem teslim alma hem teslim etme anlamına gelebildiği için
# kullanılmadı).
_PICKUP_KEYWORDS_RE = re.compile(r'\b(ALIM|ALINACAK|YÜKLEME|NEREDEN|ÇIKIŞ|ÇIKACAK)\b')
_DROPOFF_KEYWORDS_RE = re.compile(r'\b(VARIŞ|VARACAK|NEREYE|İNİŞ|TESLİM YERİ|TESLİM EDİLECEK)\b')


def _find_locations_in_line(line, district_lookup_map):
    """Büyük harfe çevrilmiş tek bir satır metninde geçen TÜM il eşleşmelerini, metindeki
    pozisyonlarına göre sıralı olarak döner: [(pozisyon, 'İl' veya 'İl / İlçe'), ...]. Bir il
    eşleşmesinin yakınında (40 karakter içinde) o ile ait bir ilçe adı da geçiyorsa, daha
    spesifik "İl / İlçe" biçiminde döner."""
    matches = []
    for m in _PROVINCE_RE.finditer(line):
        province_upper = m.group(0)
        proper_province = _PROVINCE_BY_UPPER[province_upper]
        display = proper_province
        district_map = district_lookup_map.get(province_upper) or {}
        if district_map:
            window_start = max(0, m.start() - 40)
            window_end = m.end() + 40
            window = line[window_start:window_end]
            for district_upper, proper_district in district_map.items():
                if re.search(r'\b%s\b' % re.escape(district_upper), window):
                    display = f'{proper_province} / {proper_district}'
                    break
        matches.append((m.start(), display))
    matches.sort(key=lambda pair: pair[0])
    return matches


def _detect_route_continent(text):
    """Serbest metinde (örn. Grupaj "Rota Bilgisi" sütunu) geçen il adlarını bulup, İl/İlçe/
    Mahalle Referansı tablosundaki kıta ayrımına göre rotanın hangi kıta(lar)da olduğunu
    belirler. İstanbul/Çanakkale gibi Boğaz'la ikiye bölünen iller için, metinde o ile ait
    spesifik bir ilçe adı da geçiyorsa o ilçenin kıtası kullanılır; sadece il adı tek başına
    geçiyorsa (hangi yakadan bahsedildiği belirsiz olduğu için) o eşleşmeden kıta çıkarılmaz.
    Döndürür: 'europe', 'asia', 'both' (hem Avrupa hem Asya yakalandıysa) ya da hiçbir il
    yakalanamazsa False."""
    # Lazy import: transport_address_lookup.py bu modülden önce yüklenmiyor olabilir; döngüsel
    # import riskini önlemek için fonksiyon içinde import ediliyor.
    from .transport_address_lookup import (
        _CANAKKALE_ASIA_DISTRICTS, _CANAKKALE_EUROPE_DISTRICTS, _EUROPE_ONLY_PROVINCES,
        _ISTANBUL_ASIA_DISTRICTS, _ISTANBUL_EUROPE_DISTRICTS,
    )
    if not text:
        return False
    upper_text = _tr_upper(text)
    has_europe = False
    has_asia = False
    split_provinces = {
        'İSTANBUL': (_ISTANBUL_EUROPE_DISTRICTS, _ISTANBUL_ASIA_DISTRICTS),
        'ÇANAKKALE': (_CANAKKALE_EUROPE_DISTRICTS, _CANAKKALE_ASIA_DISTRICTS),
    }
    for m in _PROVINCE_RE.finditer(upper_text):
        province_upper = m.group(0)
        if province_upper in split_provinces:
            europe_districts, asia_districts = split_provinces[province_upper]
            window = upper_text[max(0, m.start() - 40):m.end() + 40]
            if any(re.search(r'\b%s\b' % re.escape(d), window) for d in europe_districts):
                has_europe = True
            if any(re.search(r'\b%s\b' % re.escape(d), window) for d in asia_districts):
                has_asia = True
        elif province_upper in _EUROPE_ONLY_PROVINCES:
            has_europe = True
        else:
            has_asia = True
    if has_europe and has_asia:
        return 'both'
    if has_europe:
        return 'europe'
    if has_asia:
        return 'asia'
    return False


def _classify_pickup_dropoff(line, matches):
    """Bir satırda bulunan yer eşleşmelerini (ver _find_locations_in_line) alım yeri / varış
    yeri olarak sınıflandırır. Önce anahtar kelimelere (ALIM, VARIŞ, vb.) bakılır; bulunamazsa
    sezgisel bir varsayıma düşülür: tek eşleşme varsa (geriye dönük uyumluluk için) varış yeri
    kabul edilir, iki veya daha fazla eşleşme varsa ilki alım, ikincisi varış yeri kabul edilir
    ("İstanbul'dan Ankara'ya" gibi yaygın ifade sırasını yansıtır)."""
    if not matches:
        return False, False
    pickup = False
    dropoff = False
    for pos, text in matches:
        window = line[max(0, pos - 25):pos]
        if not pickup and _PICKUP_KEYWORDS_RE.search(window):
            pickup = text
        elif not dropoff and _DROPOFF_KEYWORDS_RE.search(window):
            dropoff = text
    if not pickup and not dropoff:
        if len(matches) == 1:
            dropoff = matches[0][1]
        else:
            pickup, dropoff = matches[0][1], matches[1][1]
    elif pickup and not dropoff:
        other = next((text for _, text in matches if text != pickup), False)
        dropoff = other
    elif dropoff and not pickup:
        other = next((text for _, text in matches if text != dropoff), False)
        pickup = other
    return pickup, dropoff


# Mailler bazen serbest metin değil, Excel'den kopyalanmış bir TABLO olarak geliyor (örn. "Şasi /
# Alım Yeri / Varış Yeri" sütun başlıklarıyla). html2plaintext bir HTML tabloyu düz metne
# çevirdiğinde her hücre kendi satırına düşer ve satırlar arasında boş satır kalır - bu durumda
# şasi ile yer adı AYNI SATIRDA hiç geçmez, bu yüzden _find_locations_in_line'ın satır-içi
# eşleştirmesi hiçbir şey yakalayamaz. Bu yapıyı tanıyıp sütun sırasına göre eşleştiren ayrı bir
# yol gerekiyor. Kaynağa göre (tablo mu, tek hücreli yapıştırma mı) hücre/satır ayracı da
# değişebiliyor - gözlemlenen iki gerçek biçim de farklı: biri "hücre başına bir satır, satırlar
# arasında BOŞ satır" (çift \n), diğeri her şeyin tek satıra düşüp satırlar arasında sadece ÇİFT
# BOŞLUK kalması. İkisini de "iki veya daha fazla ardışık boşluk karakteri = satır/blok sınırı,
# tek boşluk/satır sonu = aynı blok içinde hücre sınırı" kuralıyla tek bir mantıkla çözüyoruz.
_TABLE_CHASSIS_HEADERS = ('ŞASİ NO', 'ŞASI NO', 'ŞASİ', 'VIN')
_TABLE_PICKUP_HEADERS = ('ALINACAK YER', 'ALIM YERİ', 'YÜKLEME YERİ', 'YÜKLEME', 'ALIM')
_TABLE_DROPOFF_HEADERS = ('TESLİMAT YERİ', 'TESLİM YERİ', 'VARIŞ YERİ', 'VARIŞ')


def _detect_header_columns(header_text):
    """Başlık metninde (örn. 'Şasi\\nAlım Yeri\\nVarış Yeri' ya da 'Şasi Alım Yeri Varış Yeri')
    tanıdık sütun başlıklarını, metin içindeki konumlarına göre soldan sağa sıralı olarak bulur
    ve ['chassis', 'pickup', 'dropoff'] gibi bir liste döner (bulunamayan roller listede yer
    almaz). Başlıklar genelde iki kelimeli ("Alım Yeri") olduğu için TAM EŞLEŞME yerine metin
    içinde ARAMA yapılır - böylece hücreler tek kelime olsa bile başlık doğru tanınır."""
    header_upper = _tr_upper(header_text)
    found = []
    for role, phrases in (
        ('chassis', _TABLE_CHASSIS_HEADERS),
        ('pickup', _TABLE_PICKUP_HEADERS),
        ('dropoff', _TABLE_DROPOFF_HEADERS),
    ):
        for phrase in phrases:
            idx = header_upper.find(phrase)
            if idx != -1:
                found.append((idx, role))
                break
    found.sort(key=lambda pair: pair[0])
    return [role for _, role in found]


def _parse_table_structure(body_text):
    """body_text, tanıdık sütun başlıklarına (Şasi / Alım Yeri / Varış Yeri vb.) sahip bir
    tablonun düz metne çevrilmiş hali gibi görünüyorsa, [(şasi_no, alım_yeri, varış_yeri), ...]
    listesi döner (her hücre AYNEN - başka bir yer listesine karşı doğrulanmadan - kullanılır,
    çünkü zaten sütun başlığıyla etiketlenmiş, güvenilir bir değer). Böyle bir yapı
    tanınamazsa None döner - çağıran o zaman klasik aynı-satır eşleştirmesine düşer."""
    blocks = [b.strip() for b in re.split(r'\s{2,}', body_text.strip()) if b.strip()]
    if len(blocks) < 2:
        return None
    column_order = _detect_header_columns(blocks[0])
    if 'chassis' not in column_order:
        return None
    num_cols = len(column_order)
    rows = []
    for block in blocks[1:]:
        # Önce satır satır ayrılmış hücreleri dene (çok kelimeli bir değeri - örn. "Konya
        # Ereğli" - bozmadan korur); sayısı tutmazsa (hücreler tamamen tek satıra düşmüşse) boşluk
        # bazlı bölmeye düş.
        cells = [l.strip() for l in block.splitlines() if l.strip()]
        if len(cells) != num_cols:
            cells = block.split()
            if len(cells) != num_cols:
                continue
        row = dict(zip(column_order, cells))
        chassis_val = row.get('chassis')
        if chassis_val and CHASSIS_RE.fullmatch(_tr_upper(chassis_val)):
            rows.append((_tr_upper(chassis_val), row.get('pickup', False), row.get('dropoff', False)))
    return rows or None


# Mail'e Grupaj çalışma dosyası (örn. "uyarı çalışma dosyası.xlsx") eklendiğinde, sütun
# başlıkları bu teklifin Grupaj sekmesindeki (crm.lead.grupaj) alanlara otomatik eşlenir.
# Başlıklar kaynak sistemden ASCII'ye sadeleştirilmiş olarak geliyor (örn. "BASLANGICTARIHI",
# Türkçe "BAŞLANGIÇTARİHİ" değil) - bu yüzden _tr_upper yerine düz .upper() ile karşılaştırılıyor.
_GRUPAJ_HEADER_TO_FIELD = {
    'FIRMA': 'firma',
    'AKTIVITEKODU': 'activity_code',
    'GRUPAJNO': 'grupaj_no',
    'BASLANGICTARIHI': 'start_date',
    # CEKICIPLAKA bilerek eşlenmiyor: Çekici Plaka artık kendi filomuza (fleet.vehicle) bağlı bir
    # seçim alanı - Excel'deki plaka metniyle otomatik eşleştirilmiyor, Taşımacılık sekmesindeki
    # gibi kullanıcı burada kendi çekicisini elle seçiyor.
    'TASERONCEKICIPLAKA': 'subcontractor_tractor_plate',
    'ROTABILGISI': 'route_info',
    'MIKTAR': 'quantity',
    'AKTIVITEGRUPADI': 'activity_group_name',
    'KILOMETRE': 'km',
    'ARACKATSAYISI': 'vehicle_coefficient',
    'ILAVEKM': 'extra_km',
    'FATURADURUMU': 'invoice_status',
    'MT': 'mt',
}
_GRUPAJ_INT_FIELDS = {'quantity'}
_GRUPAJ_FLOAT_FIELDS = {'km', 'vehicle_coefficient', 'extra_km'}
# Aktivite Kodu ve Grupaj No, Char alanlar (bkz. crm_lead_grupaj.py) - ama Excel hücresi sayısal
# biçimliyse openpyxl int/float döner; referans numarası oldukları için ondalık gösterimi
# ("...642.0") oluşmadan temiz bir tamsayı metnine çevriliyor.
_GRUPAJ_REFERENCE_STR_FIELDS = {'grupaj_no', 'activity_code'}


def _parse_grupaj_excel(content):
    """content (bir .xlsx ekinin ham baytları), ilk satırında tanıdık Grupaj sütun başlıklarını
    (FIRMA, GRUPAJNO, ... - bkz. _GRUPAJ_HEADER_TO_FIELD) içeren bir çalışma sayfası gibi
    görünüyorsa, her veri satırı için bir {alan: değer} sözlüğü listesi döner. Tanınamayan bir
    dosyaysa (GRUPAJNO sütunu bulunamazsa) veya okunamazsa None döner - çağıran o zaman bu eki
    sessizce atlar, hata vermez."""
    if not openpyxl or not content:
        return None
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception:
        _logger.info('Grupaj eki okunamadı (xlsx değil ya da bozuk), atlanıyor.', exc_info=True)
        return None
    try:
        worksheet = workbook.worksheets[0]
        rows_iter = worksheet.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
        if not header_row:
            return None
        column_fields = [
            _GRUPAJ_HEADER_TO_FIELD.get(str(cell).strip().upper()) if cell is not None else None
            for cell in header_row
        ]
        if 'grupaj_no' not in column_fields:
            return None  # tanıdık bir Grupaj dosyası değil
        results = []
        for row in rows_iter:
            if not any(value not in (None, '') for value in row):
                continue
            vals = {}
            for field, value in zip(column_fields, row):
                if not field or value in (None, ''):
                    continue
                if field in _GRUPAJ_INT_FIELDS:
                    try:
                        vals[field] = int(value)
                    except (TypeError, ValueError):
                        continue
                elif field in _GRUPAJ_FLOAT_FIELDS:
                    try:
                        vals[field] = float(value)
                    except (TypeError, ValueError):
                        continue
                elif field == 'start_date':
                    if isinstance(value, datetime.datetime):
                        vals[field] = value.date()
                    elif isinstance(value, datetime.date):
                        vals[field] = value
                elif field in _GRUPAJ_REFERENCE_STR_FIELDS:
                    if isinstance(value, float) and value.is_integer():
                        vals[field] = str(int(value))
                    else:
                        vals[field] = str(value).strip()
                else:
                    vals[field] = str(value).strip()
            if vals:
                results.append(vals)
        return results or None
    finally:
        workbook.close()


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    @api.model
    @ormcache()
    def _get_district_lookup_map(self):
        """transport.address.lookup referans tablosundan, il başına o ile ait ilçe adlarının
        haritasını döner: {İL_BÜYÜK_HARF: {İLÇE_BÜYÜK_HARF: 'İlçe Adı', ...}, ...}. Bu, bir ilde
        geçen bir yer adının yanında ilçesi de geçiyorsa daha spesifik "İl / İlçe" şeklinde
        yakalanabilmesi içindir. Referans tablosu boşsa (veri dosyası henüz yüklenmemişse) boş
        harita döner - mail taraması o zaman sadece il seviyesinde çalışmaya devam eder, hata
        vermez."""
        rows = self.env['transport.address.lookup'].sudo().search_read(
            [], ['province', 'district'])
        by_province = defaultdict(dict)
        for row in rows:
            province = _tr_upper((row['province'] or '').strip())
            district = (row['district'] or '').strip()
            if province and district:
                by_province[province][_tr_upper(district)] = _tr_title(district)
        return dict(by_province)

    transport_pricing_method = fields.Selection(
        PRICING_METHODS, string='Ücretlendirme Yöntemi', tracking=True,
        help='Müşterinin kartındaki varsayılan ücretlendirme yöntemi buraya gelir; gerekirse bu teklif '
             'için değiştirilebilir. Sefer oluşturulduğunda sefere aktarılır.')
    transport_vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Ana Araç Ata', tracking=True, copy=False,
        domain=[('transport_state', 'in', ('available', 'returning')), ('vehicle_type', '=', 'other')],
        context={'show_transport_status': True},
        help='Bu teklif için müsait veya dönüş yolundaki bir çekici/tır atayın. Teklif birden fazla '
             'araca bölünecekse (örn. 40 araçlık talep, 5 tır), bu alanı boş bırakıp her şasi '
             'satırına (Talep Edilen Şasi Numaraları altında) kendi aracını atayabilirsiniz; bu alan '
             'sadece araç seçilmemiş satırlar için varsayılan olur.')
    transport_assignment_state = fields.Selection([
        ('pending', 'Bekliyor'),
        ('assigned', 'Atandı'),
    ], string='Atama Durumu', compute='_compute_transport_assignment_state',
        store=True, tracking=True,
        help='Teklifteki TÜM şasilere araç atanınca "Atandı" olur ve teklif Kazanıldı aşamasına '
             'geçer. Kısmi atamada (örn. 25 araçlık talebin sadece 9\'una araç seçildiyse) '
             '"Bekliyor" kalır; bu durumda da "Sefer Başlat" ile sadece atanmış olanlar için '
             'sefer başlatılabilir, kalanlar teklifte atama bekler.')
    transport_has_assignable_chassis = fields.Boolean(
        compute='_compute_transport_has_assignable_chassis',
        help='En az bir şasiye (veya ana araca) araç atanmış mı - henüz tamamı atanmamış olsa '
             'bile "Sefer Başlat" düğmesinin görünmesi için bu yeterlidir.')
    transport_driver_id = fields.Many2one(
        'hr.employee', string='Şoför', related='transport_vehicle_id.transport_driver_id', readonly=True)
    transport_trailer_id = fields.Many2one(
        'transport.trailer', string='Dorse', related='transport_vehicle_id.current_trailer_id', readonly=True)
    transport_trip_ids = fields.One2many('transport.trip', 'lead_id', string='Seferler')
    transport_trip_count = fields.Integer(compute='_compute_transport_trip_count')
    transport_trip_name = fields.Char(
        string='Sefer No', compute='_compute_transport_trip_name', store=True,
        help='Bu tekliften oluşturulan sefer(ler)in numarası. Teklif birden fazla araca '
             'bölündüyse, birden çok sefer numarası virgülle ayrılarak gösterilir.')
    transport_chassis_ids = fields.One2many(
        'crm.lead.chassis', 'lead_id', string='Talep Edilen Şasi Numaraları')
    transport_chassis_count = fields.Integer(compute='_compute_transport_chassis_count')
    transport_fuel_limit = fields.Float(
        string='Kullanılabilir Yakıt Limiti (Litre)',
        help='Bu teklif/sefer için şoförün kullanabileceği mazot limiti, litre olarak girilir '
             '(örn. 300). Bilgi amaçlıdır.')
    grupaj_ids = fields.One2many('crm.lead.grupaj', 'lead_id', string='Grupaj Satırları')

    @api.depends('transport_trip_ids')
    def _compute_transport_trip_count(self):
        for lead in self:
            lead.transport_trip_count = len(lead.transport_trip_ids)

    @api.depends('transport_trip_ids.name')
    def _compute_transport_trip_name(self):
        for lead in self:
            lead.transport_trip_name = ', '.join(lead.transport_trip_ids.mapped('name')) or False

    @api.depends('transport_chassis_ids')
    def _compute_transport_chassis_count(self):
        for lead in self:
            lead.transport_chassis_count = len(lead.transport_chassis_ids)

    @api.depends('transport_vehicle_id', 'transport_chassis_ids.vehicle_id')
    def _compute_transport_assignment_state(self):
        for lead in self:
            if lead.transport_chassis_ids:
                fully_assigned = all(
                    (chassis.vehicle_id or lead.transport_vehicle_id)
                    for chassis in lead.transport_chassis_ids
                )
                lead.transport_assignment_state = 'assigned' if fully_assigned else 'pending'
            else:
                lead.transport_assignment_state = 'assigned' if lead.transport_vehicle_id else 'pending'

    @api.depends('transport_vehicle_id', 'transport_chassis_ids.vehicle_id')
    def _compute_transport_has_assignable_chassis(self):
        for lead in self:
            if lead.transport_chassis_ids:
                lead.transport_has_assignable_chassis = any(
                    (chassis.vehicle_id or lead.transport_vehicle_id)
                    for chassis in lead.transport_chassis_ids
                )
            else:
                lead.transport_has_assignable_chassis = bool(lead.transport_vehicle_id)

    @api.onchange('partner_id')
    def _onchange_partner_id_transport_pricing(self):
        if (self.partner_id and self.partner_id.transport_pricing_method
                and not self.transport_pricing_method):
            self.transport_pricing_method = self.partner_id.transport_pricing_method

    def write(self, vals):
        previous_vehicle_by_id = {}
        if 'transport_vehicle_id' in vals:
            previous_vehicle_by_id = {lead.id: lead.transport_vehicle_id for lead in self}
        res = super().write(vals)
        if 'transport_vehicle_id' in vals:
            for lead in self:
                previous_vehicle = previous_vehicle_by_id.get(lead.id)
                if lead.transport_vehicle_id and lead.transport_vehicle_id != previous_vehicle:
                    lead._notify_transport_driver()
            self._sync_won_stage()
        return res

    def _sync_won_stage(self):
        """Teklifin aşamasını atama durumuna göre senkronize eder: tamamen araç atanmışsa
        (ana araç veya her şasi satırının kendi aracı) Kazanıldı'ya, atama kaldırılmışsa ve teklif
        Kazanıldı aşamasındaysa geri Teklif'e alır."""
        proposition_stage = self.env.ref('crm.stage_lead3', raise_if_not_found=False)
        for lead in self:
            if lead.transport_assignment_state == 'assigned':
                if lead.type == 'opportunity' and not lead.stage_id.is_won:
                    lead.action_set_won()
            elif lead.stage_id.is_won and proposition_stage:
                lead.stage_id = proposition_stage.id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('transport_pricing_method') and vals.get('partner_id'):
                partner = self.env['res.partner'].browse(vals['partner_id'])
                if partner.transport_pricing_method:
                    vals['transport_pricing_method'] = partner.transport_pricing_method
        leads = super().create(vals_list)
        for lead in leads:
            if lead.transport_vehicle_id:
                lead._notify_transport_driver()
        return leads

    def _notify_transport_driver(self):
        self.ensure_one()
        vehicle = self.transport_vehicle_id
        driver = vehicle.transport_driver_id
        if not driver:
            return
        partner = driver.work_contact_id
        body = self.env._(
            '%(vehicle)s plakalı araç bu teklife atandı: %(lead)s. Lütfen sefere hazır olun.',
            vehicle=vehicle.license_plate, lead=self.name,
        )
        self.message_post(body=body, partner_ids=partner.ids if partner else [])

    def action_start_trip(self):
        """Teklifteki şasilerden ARAÇ ATANMIŞ olanları kendi aracına göre gruplar ve her araç için
        ayrı bir sefer taslağı oluşturur - 40 araçlık bir talep 5 tıra bölünmüşse, 5 ayrı sefer
        açılır. Henüz araç atanmamış şasiler varsa onlar için sefer açılmaz, teklifte atama
        bekleyerek kalır; tamamı atanana kadar bekletmeye gerek yoktur, parça parça
        gönderilebilir."""
        self.ensure_one()
        trips, skipped = self._create_trips_from_chassis(self.transport_chassis_ids)
        if not trips:
            raise UserError('\n'.join(skipped) or 'Bu teklifte taşınacak araç (şasi no) bulunmuyor.')
        return self._trips_open_action(trips)

    def _create_trips_from_chassis(self, chassis_records):
        """Verilen şasi kayıtlarından (bu teklife ait), ARAÇ ATANMIŞ olanları kendi aracına göre
        gruplar (satırda araç seçilmemişse ana araç kullanılır) ve her araç için ayrı bir sefer
        taslağı oluşturur. Henüz araç atanmamış satırlar bu seferin dışında bırakılır (hata
        vermez) - büyük bir talep parça parça atanıp aşamalı olarak sefere dönüştürülebilir. Daha
        önce sefere dönüştürülmüş satırlar (trip_line_id dolu) atlanır, aynı şasi iki kez sefere
        eklenmez. Zaten yolda olan bir araç varsa o grup da atlanır; o araç için mevcut seferin
        "Yolda Yeni Müşteri/Araç Ekle" ekranı kullanılmalıdır. Hem tüm teklifin sefere
        dönüştürülmesinde (action_start_trip) hem de seçili bir alt kümeden sefer oluşturmada
        (crm.lead.chassis.action_create_trip_from_selection) kullanılır.
        Returns: (oluşturulan seferler, atlanan gruplar için açıklama metinleri)."""
        self.ensure_one()
        pending_records = chassis_records.filtered(lambda chassis: not chassis.trip_line_id)
        chassis_by_vehicle = defaultdict(lambda: self.env['crm.lead.chassis'])
        unassigned = self.env['crm.lead.chassis']
        for chassis in pending_records:
            vehicle = chassis.vehicle_id or self.transport_vehicle_id
            if not vehicle:
                unassigned |= chassis
            else:
                chassis_by_vehicle[vehicle.id] |= chassis

        skipped = []
        if unassigned:
            skipped.append(self.env._(
                'Şu şasi numaralarına henüz araç atanmadı, bu sefer biriminde dışarıda bırakıldı: '
                '%(chassis)s. Araç atandığında "Sefer Başlat" tekrar çalıştırılabilir.',
                chassis=', '.join(unassigned.mapped('chassis_number')),
            ))
        if not chassis_by_vehicle:
            return self.env['transport.trip'], skipped

        trips = self.env['transport.trip']
        for vehicle_id, chassis_group in chassis_by_vehicle.items():
            vehicle = self.env['fleet.vehicle'].browse(vehicle_id)
            active_trip = self.env['transport.trip'].search([
                ('vehicle_id', '=', vehicle_id), ('state', '=', 'confirmed'),
            ], limit=1)
            if active_trip:
                # This truck is already mid-trip for another job: don't fight over its state with a
                # second trip record, these chassis need to be added onto the ongoing trip instead.
                skipped.append(self.env._(
                    '%(vehicle)s zaten bir seferde (%(trip)s); %(count)s araç bu sefere elle eklenmeli '
                    '("Yolda Yeni Müşteri/Araç Ekle").',
                    vehicle=vehicle.license_plate, trip=active_trip.name, count=len(chassis_group),
                ))
                continue
            trip_vals = {
                'lead_id': self.id,
                'vehicle_id': vehicle_id,
                'cargo_line_ids': [
                    (0, 0, {
                        'chassis_number': chassis.chassis_number,
                        'lead_id': self.id,
                        'note': chassis.note,
                        'pickup_location': chassis.pickup_location,
                        'destination': chassis.destination,
                    })
                    for chassis in chassis_group
                ],
            }
            if self.transport_pricing_method:
                trip_vals['pricing_method'] = self.transport_pricing_method
            trip = self.env['transport.trip'].create(trip_vals)
            # Bu şasileri yeni oluşan sefer satırlarına bağla ki aynı şasi tekrar "Sefer Başlat"
            # çalıştırıldığında (örn. kalan şasilere de araç atanınca) ikinci kez sefere eklenmesin.
            line_by_chassis_number = {line.chassis_number: line for line in trip.cargo_line_ids}
            for chassis in chassis_group:
                line = line_by_chassis_number.get(chassis.chassis_number)
                if line:
                    chassis.trip_line_id = line.id
            trips |= trip

        if skipped:
            self.message_post(body='<br/>'.join(skipped))
        return trips, skipped

    def _trips_open_action(self, trips):
        if len(trips) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Sefer',
                'res_model': 'transport.trip',
                'view_mode': 'form',
                'res_id': trips.id,
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Seferler (%s araç)' % len(trips),
            'res_model': 'transport.trip',
            'view_mode': 'list,form',
            'domain': [('id', 'in', trips.ids)],
        }

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        lead = super().message_new(msg_dict, custom_values=custom_values)
        lead._extract_chassis_from_email(msg_dict)
        lead._extract_grupaj_from_email(msg_dict)
        return lead

    def message_update(self, msg_dict, update_vals=None):
        res = super().message_update(msg_dict, update_vals=update_vals)
        self._extract_chassis_from_email(msg_dict)
        self._extract_grupaj_from_email(msg_dict)
        return res

    def _extract_grupaj_from_email(self, msg_dict):
        """Gelen mailde tanıdık Grupaj sütun başlıklarına (FIRMA, GRUPAJNO, ... - bkz.
        _parse_grupaj_excel) sahip bir Excel (.xlsx) eki varsa, içindeki her satırı bu teklifin
        Grupaj sekmesine (crm.lead.grupaj) otomatik satır olarak ekler. Tanınmayan ekler
        (Grupaj formatında olmayan dosyalar) sessizce atlanır."""
        self.ensure_one()
        for attachment in msg_dict.get('attachments') or []:
            filename, content = attachment[0], attachment[1]
            if not filename or not filename.lower().endswith(('.xlsx', '.xls')):
                continue
            rows = _parse_grupaj_excel(content)
            if not rows:
                continue
            self.env['crm.lead.grupaj'].create([
                dict(row, lead_id=self.id) for row in rows
            ])

    def _extract_chassis_from_email(self, msg_dict):
        """Gelen mailin konusu ve metninde 17 karakterlik şasi no (VIN) deseni arar, bulduklarını
        bu teklifin 'Talep Edilen Şasi Numaraları' listesine ekler (zaten varsa tekrar eklemez).
        Alım yeri (pickup_location) ve varış yeri (destination) iki farklı yoldan yakalanmaya
        çalışılır:
        1. Mail, "Şasi / Alım Yeri / Varış Yeri" gibi sütun başlıklarına sahip bir TABLO olarak
           gelmişse (örn. Excel'den kopyala-yapıştır) - bkz. _parse_table_structure - her hücre
           sütun sırasına göre doğrudan (başka bir listeye karşı doğrulanmadan) kullanılır.
        2. Aksi halde, bir şasi numarasıyla AYNI SATIRDA geçen il (gerekirse ilçesiyle) adları
           aranır - bkz. _find_locations_in_line / _classify_pickup_dropoff. Örn. "...300718
           Alım: İstanbul Varış: Adıyaman"; tek yer adı geçen "...300718 - Adıyaman" gibi
           satırlarda (geriye dönük uyum için) o yer varış yeri kabul edilir.
        İki yöntem de birlikte çalışır: tablo satırlarıyla yakalanmış bir şasi varsa, aynı-satır
        taraması onu tekrar ezmez; tabloda olmayıp serbest metinde geçen başka şasiler de ayrıca
        yakalanabilir."""
        self.ensure_one()
        subject = msg_dict.get('subject') or ''
        body_text = html2plaintext(msg_dict.get('body') or '')
        existing = set(self.transport_chassis_ids.mapped('chassis_number'))
        found = {}

        table_rows = _parse_table_structure(body_text)
        if table_rows:
            for chassis_number, pickup, dropoff in table_rows:
                if chassis_number in existing or chassis_number in found:
                    continue
                found[chassis_number] = (pickup, dropoff)

        district_lookup_map = self._get_district_lookup_map()
        for raw_line in f'{subject}\n{body_text}'.splitlines():
            line = _tr_upper(raw_line)
            chassis_in_line = [m.group(0) for m in CHASSIS_RE.finditer(line)]
            if not chassis_in_line:
                continue
            locations = _find_locations_in_line(line, district_lookup_map)
            pickup, dropoff = _classify_pickup_dropoff(line, locations)
            for chassis_number in chassis_in_line:
                if chassis_number in existing or chassis_number in found:
                    continue
                found[chassis_number] = (pickup, dropoff)
        if not found:
            return
        self.env['crm.lead.chassis'].create([
            {
                'lead_id': self.id, 'chassis_number': number,
                'pickup_location': pickup, 'destination': dropoff,
            }
            for number, (pickup, dropoff) in sorted(found.items())
        ])

    def action_view_transport_trips(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Seferler',
            'res_model': 'transport.trip',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
        }

    def action_suggest_vehicle(self):
        """Müsait/dönüş yolundaki araçları, en uzun süredir boş duranı önde göstererek (ve
        şoförün bu ay kat ettiği kmyi yanında göstererek) sıralı bir liste olarak açar. Dispatcher
        listeden birini seçip "Bu Aracı Ata" ile bu teklifin Ana Aracı olarak atayabilir - otomatik
        tek bir atama yapmaz, karar her zaman kullanıcıda kalır."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Araç/Şoför Öner (En Uzun Süredir Müsait + En Az Km Yapan Şoför Önde)',
            'res_model': 'fleet.vehicle',
            'view_mode': 'list,form',
            'view_id': self.env.ref('transport_fleet.transport_vehicle_suggest_view_list').id,
            'domain': [('vehicle_type', '=', 'other'), ('transport_state', 'in', ('available', 'returning'))],
            'context': {'show_transport_status': True, 'suggest_for_lead_id': self.id},
            'target': 'new',
        }


class CrmLeadChassis(models.Model):
    _name = 'crm.lead.chassis'
    _description = 'Teklif - Talep Edilen Şasi No'
    _rec_name = 'chassis_number'
    _order = 'id'

    _chassis_unique = models.Constraint(
        'UNIQUE(lead_id, chassis_number)',
        'Bu şasi numarası bu teklifte zaten kayıtlı!',
    )

    lead_id = fields.Many2one('crm.lead', required=True, ondelete='cascade')
    chassis_number = fields.Char(string='Şasi No', required=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', string='Araç',
        domain=[('transport_state', 'in', ('available', 'returning')), ('vehicle_type', '=', 'other')],
        context={'show_transport_status': True},
        help='Bu şasi hangi çekiciyle taşınacak? Boş bırakılırsa teklifin Ana Aracı kullanılır. '
             'Büyük bir talebi (örn. 40 araç) birkaç çekiciye bölmek için her satıra ayrı araç seçin.')
    note = fields.Char(string='Not')
    pickup_location = fields.Char(
        string='Alım Yeri',
        help='Bu şasinin teslim alınacağı yer. Gelen mailde şasi numarasıyla aynı satırda bir '
             'il/ilçe adı "alım, yükleme, nereden, çıkış" gibi bir ifadeyle (veya satırda ikinci '
             'bir yer adıyla) yakalanırsa otomatik doldurulur; elle de değiştirilebilir. Sefer '
             'satırına aktarılır.')
    destination = fields.Char(
        string='Varış Yeri',
        help='Bu şasinin teslim edileceği yer. Gelen mailde şasi numarasıyla aynı satırda bir il '
             'adı yakalanırsa otomatik doldurulur; elle de değiştirilebilir. Sefer satırına '
             'aktarılır.')
    trip_line_id = fields.Many2one(
        'transport.trip.line', string='Sefer Satırı', readonly=True, copy=False,
        help='Bu şasi hangi sefer satırına dönüştürüldü. Doluysa bu şasi zaten bir sefere '
             'eklenmiştir, "Sefer Başlat" / "Sefer Oluştur" tekrar çalıştırıldığında atlanır.')
    trip_id = fields.Many2one(
        'transport.trip', string='Sefer No', related='trip_line_id.trip_id', store=True,
        help='Bu şasinin dönüştürüldüğü seferin numarası (örn. SEFER/2026/0055).')

    @api.model_create_multi
    def create(self, vals_list):
        chassis_list = super().create(vals_list)
        for chassis in chassis_list.filtered('vehicle_id'):
            chassis._notify_driver()
        chassis_list.mapped('lead_id')._sync_won_stage()
        return chassis_list

    def action_create_trip_from_selection(self):
        """Çoklu araç atama penceresinde (crm_lead_chassis_action_bulk) seçilen şasi satırlarından
        doğrudan sefer(ler) oluşturur - bound bir ir.actions.server olarak o liste görünümünün
        "Aksiyon" menüsünde belirir. Seçim birden fazla teklife ait olabilir; her teklif için
        kendi şasileriyle ayrı gruplama yapılır."""
        if not self:
            raise UserError('Önce sefer oluşturmak istediğiniz satırları seçmelisiniz.')
        trips = self.env['transport.trip']
        skipped = []
        for lead in self.mapped('lead_id'):
            lead_chassis = self.filtered(lambda chassis: chassis.lead_id == lead)
            lead_trips, lead_skipped = lead._create_trips_from_chassis(lead_chassis)
            trips |= lead_trips
            skipped += lead_skipped
        if not trips:
            if self.filtered('trip_line_id') and all(chassis.trip_line_id for chassis in self):
                raise UserError('Seçili satırların hepsi zaten bir sefere eklenmiş.')
            raise UserError('\n'.join(skipped) or 'Seçili satırlardan sefer oluşturulamadı.')
        return self.env['crm.lead']._trips_open_action(trips)

    def write(self, vals):
        res = super().write(vals)
        if 'vehicle_id' in vals:
            for chassis in self.filtered('vehicle_id'):
                chassis._notify_driver()
            self.mapped('lead_id')._sync_won_stage()
        return res

    def _notify_driver(self):
        self.ensure_one()
        vehicle = self.vehicle_id
        driver = vehicle.transport_driver_id
        if driver and driver.work_contact_id:
            self.lead_id.message_post(
                body=self.env._(
                    '%(vehicle)s plakalı araç, bu teklifteki %(chassis)s şasili araca atandı. '
                    'Lütfen sefere hazır olun.',
                    vehicle=vehicle.license_plate, chassis=self.chassis_number,
                ),
                partner_ids=driver.work_contact_id.ids,
            )
