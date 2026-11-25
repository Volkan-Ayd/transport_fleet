from odoo import api, fields, models

# Trakya'da olup tamamı Avrupa kıtasında kalan iller (ilçe ayrımı gerekmez).
_EUROPE_ONLY_PROVINCES = {'EDİRNE', 'KIRKLARELİ', 'TEKİRDAĞ'}

# İstanbul, Boğaz ile ikiye bölündüğü için kıta ilçe bazında belirlenir. Burada olmayan
# İstanbul ilçeleri (Adalar, Ataşehir, Beykoz, Çekmeköy, Kadıköy, Kartal, Maltepe, Pendik,
# Sancaktepe, Şile, Sultanbeyli, Tuzla, Ümraniye, Üsküdar) Anadolu (Asya) yakasındadır.
_ISTANBUL_EUROPE_DISTRICTS = {
    'ARNAVUTKÖY', 'AVCILAR', 'BAĞCILAR', 'BAHÇELİEVLER', 'BAKIRKÖY', 'BAŞAKŞEHİR',
    'BAYRAMPAŞA', 'BEŞİKTAŞ', 'BEYLİKDÜZÜ', 'BEYOĞLU', 'BÜYÜKÇEKMECE', 'ÇATALCA',
    'ESENLER', 'ESENYURT', 'EYÜPSULTAN', 'FATİH', 'GAZİOSMANPAŞA', 'GÜNGÖREN',
    'KAĞITHANE', 'KÜÇÜKÇEKMECE', 'SARIYER', 'SİLİVRİ', 'ŞİŞLİ', 'SULTANGAZİ',
    'ZEYTİNBURNU',
}

# Çanakkale de Çanakkale Boğazı ile ikiye bölünür. Gelibolu/Eceabat/Gökçeada Avrupa
# (Trakya/Gelibolu Yarımadası) yakasında; Merkez (şehir merkezi dahil) ve diğerleri
# Anadolu (Asya) yakasındadır.
_CANAKKALE_EUROPE_DISTRICTS = {'GELİBOLU', 'ECEABAT', 'GÖKÇEADA'}

# Yukarıdaki iki setin "tersi" - serbest metinde geçen bir ilçe adının hangi yakaya ait
# olduğunu doğrudan kontrol edebilmek için (örn. crm_lead_grupaj.py'deki rota kıtası
# yakalama) ayrıca Asya yakası ilçeleri de açıkça listeleniyor.
_ISTANBUL_ASIA_DISTRICTS = {
    'ADALAR', 'ATAŞEHİR', 'BEYKOZ', 'ÇEKMEKÖY', 'KADIKÖY', 'KARTAL', 'MALTEPE', 'PENDİK',
    'SANCAKTEPE', 'ŞİLE', 'SULTANBEYLİ', 'TUZLA', 'ÜMRANİYE', 'ÜSKÜDAR',
}
_CANAKKALE_ASIA_DISTRICTS = {
    'AYVACIK', 'BAYRAMİÇ', 'BİGA', 'BOZCAADA', 'ÇAN', 'EZİNE', 'LAPSEKİ', 'MERKEZ', 'YENİCE',
}


class TransportAddressLookup(models.Model):
    _name = 'transport.address.lookup'
    _description = 'Türkiye İl/İlçe/Mahalle Referansı'
    _rec_name = 'neighborhood'
    _order = 'province, district, neighborhood'

    province = fields.Char(string='İl', required=True, index=True)
    district = fields.Char(string='İlçe', required=True, index=True)
    subdistrict = fields.Char(string='Semt/Bucak/Belde')
    neighborhood = fields.Char(string='Mahalle')
    postal_code = fields.Char(string='Posta Kodu', index=True)
    continent = fields.Selection([
        ('europe', 'Avrupa'),
        ('asia', 'Asya'),
    ], string='Kıta', compute='_compute_continent', store=True,
        help='İstanbul ve Çanakkale, Boğaz ile ikiye bölündüğü için ilçeye göre; Edirne, '
             'Kırklareli ve Tekirdağ tamamen Avrupa; diğer tüm iller Asya kıtasında kabul edilir.')

    @api.depends('province', 'district')
    def _compute_continent(self):
        for rec in self:
            province = (rec.province or '').strip()
            district = (rec.district or '').strip()
            if province in _EUROPE_ONLY_PROVINCES:
                rec.continent = 'europe'
            elif province == 'İSTANBUL':
                rec.continent = 'europe' if district in _ISTANBUL_EUROPE_DISTRICTS else 'asia'
            elif province == 'ÇANAKKALE':
                rec.continent = 'europe' if district in _CANAKKALE_EUROPE_DISTRICTS else 'asia'
            else:
                rec.continent = 'asia'
