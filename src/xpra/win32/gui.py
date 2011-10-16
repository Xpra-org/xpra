# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011 Antoine Martin <antoine@nagafix.co.uk>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

import os.path

from xpra.platform.client_extras_base import ClientExtrasBase
from wimpiggy.log import Logger
log = Logger()


# The data for this table can be found mostly here:
# http://msdn.microsoft.com/en-us/library/aa912040.aspx
# and here:
# http://support.microsoft.com/kb/278957
# Format:
# Language identifier: (Sublanguage - locale, Language, Default code page, X11 keymap, Language code)
UNICODE=-1
WIN32_LAYOUTS = {
           1025: ("Saudi Arabia",   "Arabic",                   1356,   "ar",       "ARA"),
           1026: ("Bulgaria",       "Bulgarian",                1251,   "bg",       "BGR"),
           1027: ("Spain",          "Catalan",                  1252,   "",         "CAT"),
           1028: ("Taiwan",         "Chinese",                  950,    "tw",       "CHT"),
           1029: ("Czech",          "Czech",                    1250,   "cz",       "CSY"),
           1030: ("Denmark",        "Danish",                   1252,   "dk",       "DAN"),
           1031: ("Germany",        "German",                   1252,   "de",       "DEU"),
           1032: ("Greece",         "Greek",                    1253,   "gr",       "ELL"),
           1033: ("United States",  "English",                  1252,   "en_US",    "USA"),
           1034: ("Spain (Traditional sort)", "Spanish",        1252,   "sp",       "ESP"),
           1035: ("Finland",        "Finnish",                  1252,   "fi",       "FIN"),
           1036: ("France",         "French",                   1252,   "fr",       "FRA"),
           1037: ("Israel",         "Hebrew",                   1255,   "",         "HEB"),
           1038: ("Hungary",        "Hungarian",                1250,   "hu",       "HUN"),
           1039: ("Iceland",        "Icelandic",                1252,   "",         "ISL"),
           1040: ("Italy",          "Italian",                  1252,   "it",       "ITA"),
           1041: ("Japan",          "Japanese",                 932,    "jp",       "JPN"),
           1042: ("Korea",          "Korean",                   949,    "kr",       "KOR"),
           1043: ("Netherlands",    "Dutch",                    1252,   "",         "NLD"),
           1044: ("Norway (Bokmål)","Norwegian",                1252,   "no",       "NOR"),
           1045: ("Poland",         "Polish",                   1250,   "po",       "PLK"),
           1046: ("Brazil",         "Portuguese",               1252,   "pt_br",    "PTB"),
           1048: ("Romania",        "Romanian",                 1250,   "ro",       "ROM"),
           1049: ("Russia",         "Russian",                  1251,   "ru",       "RUS"),
           1050: ("Croatia",        "Croatian",                 1250,   "",         "HRV"),
           1051: ("Slovakia",       "Slovakian",                1250,   "sk",       "SKY"),
           1052: ("Albania",        "Albanian",                 1250,   "",         "SQI"),
           1053: ("Sweden",         "Swedish",                  1252,   "sv",       "SVE"),
           1054: ("Thailand",       "Thai",                     874,    "th",       "THA"),
           1055: ("Turkey",         "Turkish",                  1254,   "tr",       "TRK"),
           1056: ("Pakistan",       "Urdu",                     1256,   "",         "URP"),
           1057: ("Indonesia (Bahasa)", "Indonesian",           1252,   "id",       "IND"),
           1058: ("Ukraine",        "Ukrainian",                1251,   "uk",       "UKR"),
           1059: ("Belarus",        "Belarusian",               1251,   "",         "BEL"),
           1060: ("Slovenia",       "Slovenian",                1250,   "",         "SLV"),
           1061: ("Estonia",        "Estonian",                 1257,   "",         "ETI"),
           1062: ("Latvia",         "Latvian",                  1257,   "",         "LVI"),
           1063: ("Lithuania",      "Lithuanian",               1257,   "",         "LTH"),
           1065: ("Iran",           "Farsi",                    1256,   "",         "FAR"),
           1066: ("Viet Nam",       "Vietnamese",               1258,   "",         "VIT"),
           1067: ("Armenia",        "Armenian",                 UNICODE,"",         "HYE"),
           1068: ("Azerbaijan (Latin)", "Azeri",                1254,   "",         "AZE"),
           1069: ("Spain",          "Basque",                   1252,   "",         "EUQ"),
           1071: ("F.Y.R.O. Macedonia", "F.Y.R.O. Macedonia",   1251,   "",         "MKI"),
           1078: ("South Africa",   "Afrikaans",                1252,   "",         "AFK"),
           1079: ("Georgia",        "Georgian",                 UNICODE,"",         "KAT"),
           1080: ("Faroe Islands",  "Faroese",                  1252,   "",         "FOS"),
           1081: ("India",          "Hindi",                    UNICODE,"",         "HIN"),
           1086: ("Malaysia",       "Malay",                    1252,   "",         "MSL"),
           1087: ("Kazakstan",      "Kazakh",                   1251,   "",         "KKZ"),
           1088: ("Kyrgyzstan",     "Kyrgyz",                   1251,   "",         "KYR"),
           1089: ("Kenya",          "Swahili",                  1252,   "",         "SWK"),
           1091: ("Uzbekistan (Latin)", "Uzbek",                1254,   "",         "UZB"),
           1092: ("Tatarstan",      "Tatar",                    1251,   "",         "TTT"),
           1094: ("India (Gurmukhi script)", "Punjabi",         UNICODE,"",         "PAN"),
           1095: ("India",          "Gujarati",                 UNICODE,"",         "GUJ"),
           1097: ("India",          "Tamil",                    UNICODE,"",         "TAM"),
           1098: ("India (Telugu script)", "Telugu",            UNICODE,"",         "TEL"),
           1099: ("India (Kannada script)", "Kannada",          UNICODE,"",         "KAN"),
           1102: ("India",          "Marathi",                  UNICODE,"",         "MAR"),
           1103: ("India",          "Sanskrit",                 UNICODE,"",         "SAN"),
           1104: ("Mongolia",       "Mongolian (Cyrillic)",     1251,   "",         "MON"),
           1110: ("Spain",          "Galician",                 1252,   "",         "GLC"),
           1111: ("India",          "Konkani",                  UNICODE,"",         "KNK"),
           1114: ("Syria",          "Syriac",                   UNICODE,"",         "SYR"),
           1125: ("Maldives",       "Divehi",                   UNICODE,"",         "DIV"),
           2049: ("Iraq",           "Arabic",                   1256,   "ar",       "ARI"),
           2052: ("PRC",            "Chinese, Simplified",      0,      "cn",       "CHS"),
           2055: ("Switzerland",    "German",                   1252,   "de",       "DES"),
           2057: ("UK",             "English",                  1252,   "gb",       "ENG"),
           2058: ("Mexico",         "Spanish",                  1252,   "sp",       "ESM"),
           2060: ("Benelux",        "French",                   1252,   "be",       "FRB"),
           2064: ("Switzerland",    "Italian",                  1252,   "it",       "ITS"),
           2067: ("Belgium",        "Dutch",                    1252,   "",         "NLB"),
           2068: ("Norway (Nynorsk)", "Norwegian",              1252,   "",         "NON"),
           2070: ("Portugal",       "Portuguese",               1252,   "pt",       "PTG"),
           2074: ("Serbia (Latin)", "Serbian",                  1250,   "",         "SRL"),
           2077: ("Finland",        "Swedish",                  1252,   "sv",       "SVF"),
           2092: ("Azerbaijan (Cyrillic)", "Azeri",             1251,   "",         "AZE"),
           2110: ("Brunei Darussalam", "Malay",                 1252,   "",         "MSB"),
           2115: ("Uzbekistan (Cyrillic)", "Uzbek",             1251,   "",         "UZB"),
           3073: ("Egypt",          "Arabic",                   1256,   "ar",       "ARE"),
           3076: ("Hong Kong SAR",  "Chinese",                  950,    "",         "ZHH"),
           3079: ("Austria",        "German",                   1252,   "",         "DEA"),
           3081: ("Australia",      "English",                  1252,   "au",       "ENA"),
           3082: ("Spain (International sort)", "Spanish",      1252,   "sp",       "ESN"),
           3084: ("Canada",         "French",                   1252,   "fr_ca",    "FRC"),
           3098: ("Serbia (Cyrillic)", "Serbian",               1251,   "",         "SRB"),
           4097: ("Libya",          "Arabic",                   1256,   "ar",       "ARL"),
           4100: ("Singapore",      "Chinese",                  936,    "",         "ZHI"),
           4103: ("Luxembourg",     "German",                   1252,   "de",       "DEL"),
           4105: ("Canada",         "English",                  1252,   "us_ca",    "ENC"),
           4106: ("Guatemala",      "Spanish",                  1252,   "sp",       "ESG"),
           4108: ("Switzerland",    "French",                   1252,   "fr",       "FRS"),
           5121: ("Algeria",        "Arabic",                   1256,   "ar",       "ARG"),
           5124: ("Macao SAR",      "Chinese",                  950,    "",         "ZHM"),
           5127: ("Liechtenstein",  "German",                   1252,   "de",       "DEC"),
           5129: ("New Zealand",    "English",                  1252,   "en_nz",    "ENZ"),
           5130: ("Costa Rica",     "Spanish",                  1252,   "sp",       "ESC"),
           5132: ("Luxembourg",     "French",                   1252,   "fr",       "FRL"),
           6145: ("Morocco",        "Arabic",                   1256,   "ar",       "ARM"),
           6153: ("Ireland",        "English",                  1252,   "en",       "ENI"),
           6154: ("Panama",         "Spanish",                  1252,   "sp",       "ESA"),
           6156: ("Monaco",         "French",                   1252,   "fr",       "FRM"),
           7169: ("Tunisia",        "Arabic",                   1256,   "ar",       "ART"),
           7177: ("South Africa",   "English",                  1252,   "en",       "ENS"),
           7178: ("Dominican Republic", "Spanish",              1252,   "sp",       "ESD"),
           8193: ("Oman",           "Arabic",                   1256,   "ar",       "ARO"),
           8201: ("Jamaica",        "English",                  1252,   "en",       "ENJ"),
           8202: ("Venezuela",      "Spanish",                  1252,   "sp",       "ESV"),
           9217: ("Yemen",          "Arabic",                   1256,   "ar",       "ARY"),
           9225: ("Caribbean",      "English",                  1252,   "en",       "ENB"),
           9226: ("Colombia",       "Spanish",                  1252,   "sp",       "ESO"),
           10241: ("Syria",         "Arabic",                   1256,   "ar",       "ARS"),
           10249: ("Belize",        "English",                  1252,   "",         "ENL"),
           10250: ("Peru",          "Spanish",                  1252,   "sp",       "ESR"),
           11265: ("Jordan",        "Arabic",                   1256,   "ar",       "ARJ"),
           11273: ("Trinidad",      "English",                  1252,   "en",       "ENT"),
           11274: ("Argentina",     "Spanish",                  1252,   "es",       "ESS"),
           12289: ("Lebanon",       "Arabic",                   1256,   "ar",       "ARB"),
           12297: ("Zimbabwe",      "English",                  1252,   "en",       "ENW"),
           12298: ("Ecuador",       "Spanish",                  1252,   "sp",       "ESF"),
           13321: ("Philippines",   "English",                  1252,   "en",       "ENP"),
           13313: ("Kuwait",        "Arabic",                   1256,   "ar",       "ARK"),
           13322: ("Chile",         "Spanish",                  1252,   "sp",       "ESL"),
           14337: ("U.A.E.",        "Arabic",                   1256,   "ar",       "ARU"),
           14345: ("Indonesia",     "English",                  1252,   "en",       ""),
           14346: ("Uruguay",       "Spanish",                  1252,   "sp",       "ESY"),
           15361: ("Bahrain",       "Arabic",                   1256,   "ar",       "ARH"),
           15369: ("Hong Kong SAR", "English",                  1252,   "en",       "ZHH"),
           15370: ("Paraguay",      "Spanish",                  1252,   "sp",       "ESZ"),
           16385: ("Qatar",         "Arabic",                   1256,   "ar",       "ARQ"),
           16393: ("India",         "English",                  1252,   "en",       ""),
           16394: ("Bolivia",       "Spanish",                  1252,   "sp",       "ESB"),
           17417: ("Malaysia",      "English",                  1252,   "en",       ""),
           17418: ("El Salvador",   "Spanish",                  1252,   "sp",       "ESE"),
           18441: ("Singapore",     "English",                  1252,   "en",       ""),
           18442: ("Honduras",      "Spanish",                  1252,   "sp",       "ESH"),
           19466: ("Nicaragua",     "Spanish",                  1252,   "sp",       "ESI"),
           20490: ("Puerto Rico",   "Spanish",                  1252,   "sp",       "ESU"),
           58378: ("LatAm",         "Spanish",                  1252,   "sp",       ""),
           58380: ("North Africa",  "French",                   1252,   "fr",       ""),
           }

class ClipboardProtocolHelper(object):
    def __init__(self, send_packet_cb):
        self.send = send_packet_cb

    def send_all_tokens(self):
        pass

    def process_clipboard_packet(self, packet):
        packet_type = packet[0]
        if packet_type == "clipboard_request":
            (_, request_id, selection, _) = packet
            self.send(["clipboard-contents-none", request_id, selection])



class ClientExtras(ClientExtrasBase):
    def __init__(self, client, opts):
        ClientExtrasBase.__init__(self, client)
        self.setup_menu()
        self.setup_tray(opts.tray_icon)

    def exit(self):
        if self.tray:
            self.tray.close()

    def can_notify(self):
        return  True

    def show_notify(self, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        if self.notify:
            self.notify(self.tray.getHWND(), summary, body, expire_timeout)



    def setup_tray(self, tray_icon_filename):
        self.tray = None
        self.notify = None
        #we wait for session_name to be set during the handshake
        #the alternative would be to implement a set_name() method
        #on the Win32Tray - but this looks too complicated
        self.client.connect("handshake-complete", self.do_setup_tray, tray_icon_filename)

    def do_setup_tray(self, client, tray_icon_filename):
        self.tray = None
        self.notify = None
        if not tray_icon_filename or not os.path.exists(tray_icon_filename):
            tray_icon_filename = self.get_icon_filename('xpra.ico')
        if not tray_icon_filename or not os.path.exists(tray_icon_filename):
            log.error("invalid tray icon filename: '%s'" % tray_icon_filename)

        try:
            from xpra.win32.win32_tray import Win32Tray
            self.tray = Win32Tray(self.client.session_name, self.activate_menu, self.quit, tray_icon_filename)
        except Exception, e:
            log.error("failed to load native Windows NotifyIcon: %s", e)
            return  #cant do balloon without tray!
        try:
            from xpra.win32.win32_balloon import notify
            self.notify = notify
        except Exception, e:
            log.error("failed to load native win32 balloon: %s", e)

    def get_keymap_spec(self):
        layout = None
        try:
            import win32api         #@UnresolvedImport
            id = win32api.GetKeyboardLayout(0) & 0xffff
            if id in WIN32_LAYOUTS:
                _, _, _, layout, code = WIN32_LAYOUTS.get(id)
                log.info("found keyboard layout '%s', code '%s' for id=%s", layout, code, id)
            if not layout:
                log.info("unknown keyboard layout for id: %s", id)
        except Exception, e:
            log.error("failed to detect keyboard layout: %s", e)
        return layout,None,None,None


    def popup_menu_workaround(self, menu):
        self.add_popup_menu_workaround(menu)
