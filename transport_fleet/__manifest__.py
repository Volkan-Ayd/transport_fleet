{
    'name': 'Taşımacılık - Filo Genişletmesi',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Fleet',
    'summary': 'Çekici, dorse, şoför ve belge takibi (Fleet genişletmesi)',
    'depends': ['fleet', 'hr', 'mail'],
    'data': [
        'security/ir.access.csv',
        'data/cron.xml',
        'views/transport_document_views.xml',
        'views/transport_trailer_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/hr_employee_views.xml',
        'views/menus.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
}
