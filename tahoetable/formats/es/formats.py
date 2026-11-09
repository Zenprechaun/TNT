# How dates and times look in Spanish (FORMAT_MODULE_PATH in settings.py).
# Month names, not numbers, so nobody has to guess between 8/11 and 11/8.
DATE_FORMAT = r"j \d\e F \d\e Y"            # 8 de noviembre de 2026
SHORT_DATE_FORMAT = "j b Y"                 # 8 nov 2026
SHORT_DATETIME_FORMAT = "j b Y, g:i a"      # 8 nov 2026, 9:15 p. m.
TIME_FORMAT = "g:i a"                       # 9:15 p. m.
