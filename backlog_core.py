# -*- coding: utf-8 -*-
"""GameBacklog 4.x — спільний шар даних, сканерів і Steam API."""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
import uuid
import webbrowser
from datetime import date
from typing import Any

try:
    import winreg
except ImportError:
    winreg = None

VERSION = "4.0"

DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "GameBacklog")
DATA_FILE = os.path.join(DATA_DIR, "games.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
ICONS_DIR = os.path.join(DATA_DIR, "icons")

STATUSES = ["want", "playing", "done", "postponed", "dropped"]
DONE_STATUSES = ("done", "dropped")
CUSTOM_STATUS_COLORS = ("#ff6b9d", "#8b7bff", "#ffb454", "#35c8ff",
                        "#3ce0a0", "#ff8a00", "#c77dff", "#4d8dff")
STATUS_ALIASES = {
    "Хочу пройти": "want", "В процесі": "playing", "Пройдено": "done",
    "Відкладено": "postponed", "Покинуто": "dropped",
    "Want to play": "want", "Playing": "playing", "Completed": "done",
    "Postponed": "postponed", "Dropped": "dropped",
}
PLATFORM_PRESETS = ["PC", "Steam", "Epic", "GOG", "Xbox", "PS5", "Switch", "Other"]
GENRE_PRESETS = ["RPG", "Action", "Adventure", "Strategy", "Indie", "Platformer",
                 "Shooter", "Horror", "Simulation", "Puzzle", "Racing", "Metroidvania"]
SORT_KEYS = ["title_asc", "title_desc", "date_desc", "score_desc",
             "hours_desc", "status", "custom"]
TOOLBAR_KEYS = ["steam", "pc", "delete", "import", "export", "compact"]
TOOLBAR_RIGHT = {"compact"}
TOOLBAR_LABELS = {"steam": "steam_add", "pc": "pc_add",
                  "delete": "delete", "import": "import", "export": "export",
                  "compact": "compact"}
TOOLBAR_GLYPHS = {"steam": "＋ Steam", "pc": "＋ PC",
                  "delete": "⌫", "import": "↧", "export": "↥",
                  "compact": "⇥"}
FIELDS = ["id", "title", "platform", "genre", "status", "score", "hours",
          "price", "link", "tags", "added", "completed", "notes", "order",
          "appid", "exe", "icon", "steam_verified", "verified_genres",
          "verified_at"]

DEFAULT_COLORS: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0b0d18", "panel": "#151331", "field": "#101227",
        "border": "#3b3468", "fg": "#eef0ff", "muted": "#9c98c9",
        "accent": "#8654ff", "accent2": "#4d8dff",
        "header_bg": "#12102a", "header_fg": "#eef0ff", "sel": "#2a2456",
        "dock": "#0b0d18", "dock_fg": "#c6b6ff",
        "card": "#191636", "card_sel": "#2a2057", "card_border": "#3b3468",
        "status_want": "#a17bff", "status_playing": "#35c8ff",
        "status_done": "#3ce0a0", "status_postponed": "#ffb454",
        "status_dropped": "#ff5d7e",
    },
    "light": {
        "bg": "#eef0fb", "panel": "#ffffff", "field": "#f5f5fd",
        "border": "#c9c3e8", "fg": "#1b1740", "muted": "#66608f",
        "accent": "#7040e8", "accent2": "#2f6ede",
        "header_bg": "#f8f7ff", "header_fg": "#1b1740", "sel": "#e8e2ff",
        "dock": "#1b1740", "dock_fg": "#e8e2ff",
        "card": "#ffffff", "card_sel": "#efe9ff", "card_border": "#c9c3e8",
        "status_want": "#7040e8", "status_playing": "#008ec4",
        "status_done": "#12996d", "status_postponed": "#c08a1e",
        "status_dropped": "#db4064",
    },
}

# Готові теми. Палітри зібрані за реальними фірмовими кольорами:
# Dota 2 — #BF2E1A red / #E7A34B radiant gold / #244F62 slate / #27AE9E teal;
# Cyberpunk 2077 — #FCEE0A yellow / #00F0FF cyan / #FF003C crimson.
THEMES: dict[str, dict[str, Any]] = {
    "classic": {
        "name": {"ru": "Класика", "en": "Classic"},
        "desc": {"ru": "Неоновий HUD, як зараз", "en": "Neon HUD, current look"},
        "palette": dict(DEFAULT_COLORS["dark"]),
    },
    "dota2": {
        "name": {"ru": "Дота 2", "en": "Dota 2"},
        "desc": {"ru": "Червоний + чорний, Aegis", "en": "Red + black, Aegis"},
        "palette": {
            # Основні кольори Dota — червоний і чорний. Золото Radiant лише другорядне.
            "bg": "#0a0708", "panel": "#150c0f", "field": "#100809",
            "border": "#4a171d", "fg": "#f4e9e7", "muted": "#a88488",
            "accent": "#bf2e1a", "accent2": "#e7a34b",
            "header_bg": "#0d0608", "header_fg": "#ffd8c8", "sel": "#361217",
            "dock": "#070405", "dock_fg": "#bf2e1a",
            "card": "#130a0d", "card_sel": "#2b0f15", "card_border": "#5a1d24",
            "status_want": "#e7a34b", "status_playing": "#bf2e1a",
            "status_done": "#6fae74", "status_postponed": "#8a6570",
            "status_dropped": "#ff3b24",
        },
    },
    "cyberpunk": {
        "name": {"ru": "Кіберпанк", "en": "Cyberpunk"},
        "desc": {"ru": "Night City: жовтий, ціан, 2077", "en": "Night City: yellow, cyan, 2077"},
        "palette": {
            "bg": "#050a0e", "panel": "#0b141a", "field": "#071116",
            "border": "#1c3a42", "fg": "#e8fbff", "muted": "#7fa9b3",
            "accent": "#fcee0a", "accent2": "#00f0ff",
            "header_bg": "#071014", "header_fg": "#fcee0a", "sel": "#163038",
            "dock": "#050a0e", "dock_fg": "#fcee0a",
            "card": "#0a161c", "card_sel": "#12303a", "card_border": "#1d4652",
            "status_want": "#fcee0a", "status_playing": "#00f0ff",
            "status_done": "#39ff88", "status_postponed": "#ff8a00",
            "status_dropped": "#ff003c",
        },
    },
    "light": {
        "name": {"ru": "Світла", "en": "Light"},
        "desc": {"ru": "Світлий запасний режим", "en": "Light fallback mode"},
        "palette": dict(DEFAULT_COLORS["light"]),
    },
}
THEME_KEYS = list(THEMES)


def custom_statuses(settings: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Глобальні статуси користувача: key / label / color."""
    if not settings:
        return []
    result = []
    for item in settings.get("custom_statuses", []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        if key and key not in STATUSES and label:
            result.append({"key": key, "label": label,
                           "color": str(item.get("color") or CUSTOM_STATUS_COLORS[0])})
    return result


STATUS_LABELS = {
    "ru": {"want": "Хочу пройти", "playing": "В процессе", "done": "Пройдено",
           "postponed": "Отложено", "dropped": "Брошено"},
    "en": {"want": "Want to play", "playing": "Playing", "done": "Completed",
           "postponed": "Postponed", "dropped": "Dropped"},
}
SORT_TEXT = {
    "ru": {"title_asc": "Название А–Я", "title_desc": "Название Я–А",
           "date_desc": "Дата добавления ↓", "score_desc": "Оценка ↓",
           "hours_desc": "Часы ↓", "status": "Статус", "custom": "Свой порядок"},
    "en": {"title_asc": "Title A–Z", "title_desc": "Title Z–A",
           "date_desc": "Date added ↓", "score_desc": "Rating ↓",
           "hours_desc": "Hours ↓", "status": "Status", "custom": "Custom order"},
}
COLOR_LABELS = {
    "ru": {"bg": "Фон", "panel": "Панели", "field": "Поля ввода",
           "border": "Границы", "fg": "Текст", "muted": "Приглушённый текст",
           "accent": "Акцент", "accent2": "Второй акцент",
           "header_bg": "Шапка", "header_fg": "Текст шапки",
           "sel": "Выделение", "dock": "Боковая вкладка", "dock_fg": "Текст вкладки",
           "card": "Карточка", "card_sel": "Карточка выбрана", "card_border": "Граница карточки",
           "status_want": "Статус: хочу", "status_playing": "Статус: в процессе",
           "status_done": "Статус: пройдено", "status_postponed": "Статус: отложено",
           "status_dropped": "Статус: брошено"},
    "en": {"bg": "Background", "panel": "Panels", "field": "Input fields",
           "border": "Borders", "fg": "Text", "muted": "Muted text",
           "accent": "Accent", "accent2": "Second accent",
           "header_bg": "Header", "header_fg": "Header text",
           "sel": "Selection", "dock": "Edge tab", "dock_fg": "Edge tab text",
           "card": "Card", "card_sel": "Selected card", "card_border": "Card border",
           "status_want": "Status: want", "status_playing": "Status: playing",
           "status_done": "Status: done", "status_postponed": "Status: postponed",
           "status_dropped": "Status: dropped"},
}

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        "app_title": "GameBacklog — игры, которые хочу пройти",
        "app_name": "GameBacklog",
        "tab_list": "Мои игры", "tab_stats": "Статистика",
        "edit": "✎ Правка", "delete": "⌫ Удалить",
        "import": "↧ Импорт", "export": "↥ Экспорт",
        "theme": "◐ Тема", "language": "文 RU/EN",
        "compact": "⇥ Свернуть", "help": "? Справка", "settings": "⚙ Настройки",
        "library_eyebrow": "БИБЛИОТЕКА  ·  {}",
        "picker_selected": "Выбрано: {}", "picker_add": "＋ Добавить",
        "hint": "Нажмите на карточку игры — справа откроется редактор. "
                "Добавляйте игры из Steam или с компьютера.",
        "empty_list": "Пока нет игр. Нажмите «＋ Steam» или «＋ PC».",
        "search": "Поиск:", "status": "Статус:", "platform": "Платформа:",
        "active_only": "Только активные", "sorting": "Сортировка:", "all": "Все",
        "editor_header": "Редактор игры", "editor_hint": "Выберите карточку слева",
        "section_main": "Основное", "section_meta": "Оценка и время",
        "section_links": "Ссылка и теги", "section_dates": "Даты и заметки",
        "section_status": "Статус", "section_launch": "Запуск",
        "section_notes": "Заметки",
        "f_title": "Название", "f_platform": "Платформа", "f_genre": "Жанр",
        "f_status": "Статус", "f_score": "Оценка (0–10)", "f_hours": "Часов",
        "f_price": "Цена, ₴", "f_link": "Ссылка", "f_tags": "Теги (через запятую)",
        "f_added": "Добавлено", "f_completed": "Дата прохождения", "f_notes": "Заметки",
        "save_changes": "✓ Сохранить", "mark_done": "✓ Пройдено",
        "close_editor": "Закрыть редактор", "launch": "▶ Запустить",
        "launch_ok": "Запущено: {}", "launch_fail": "Не удалось запустить: {}",
        "f_exe": "Путь к .exe", "browse": "Обзор…",
        "add_status": "+ Свой статус", "status_name": "Название статуса",
        "status_exists": "Такой статус уже есть.",
        "status_rename": "Переименовать статус", "status_delete": "Удалить статус",
        "status_delete_confirm": "Удалить статус «{}»? Игры с ним перейдут в «Хочу пройти».",
        "status_color": "Цвет статуса", "icon_update": "Обновить иконку",
        "icon_done": "Иконка загружена.", "icon_fail": "Не удалось загрузить иконку: {}",
        "msg_select": "Сначала выберите игру.",
        "delete_title": "Удаление", "delete_confirm": "Удалить «{}» из списка?",
        "delete_action": "Удалить", "delete_warn": "Отменить это действие нельзя.",
        "steam_add": "＋ Steam", "steam_title": "Добавить игру из Steam",
        "steam_hint": "Введите название — игры загрузятся из каталога Steam.",
        "steam_note": "Каталог Steam", "steam_search": "Поиск:",
        "steam_col_name": "Название", "steam_col_id": "AppID", "steam_col_price": "Цена",
        "steam_add_btn": "＋ Добавить", "steam_close": "Закрыть",
        "steam_wait": "Поиск…", "steam_ready": "Найдено: {}", "steam_nothing": "Ничего не найдено",
        "steam_top": "Ничего не найдено — показываем топ чарт Steam",
        "steam_error": "Не удалось загрузить данные Steam: {}",
        "steam_select": "Сначала выберите игру в результатах.",
        "steam_details": "Загрузка жанров и обложек…",
        "steam_added": "Добавлено из Steam: {}\nПропущено (уже есть): {}",
        "steam_free": "бесплатно",
        "pc_add": "＋ PC", "pc_title": "Игры на компьютере",
        "pc_hint": "Найденные установленные игры — выберите и добавьте.",
        "pc_scan": "Сканировать", "pc_browse": "Выбрать папку",
        "pc_scanning": "Поиск…", "pc_found": "Найдено: {}",
        "pc_source": "Источник", "pc_path": "Путь",
        "pc_added": "Добавлено: {}\nПропущено: {}",
        "pc_empty": "Игры не найдены. Установите Steam/Epic или выберите папку.",
        "pc_select": "Сначала выберите игру в списке.",
        "export_title": "Экспорт списка игр", "import_title": "Импорт списка игр",
        "import_prompt": ("Найдено игр: {}\n\nДА — заменить текущий список.\n"
                          "НЕТ — добавить к текущему (дубликаты пропустим)."),
        "import_done": "Импорт завершён. Игр в списке: {}",
        "export_done": "Экспортировано в:\n{}",
        "import_error": "Ошибка импорта:\n{}", "export_error": "Ошибка экспорта:\n{}",
        "saved": "Сохранено.", "load_error": "Не удалось прочитать файл данных:\n{}",
        "save_error": "Не удалось сохранить данные:\n{}",
        "empty_export": "Список пуст — экспортировать нечего.",
        "stats_header": "Статистика вашего бэклога", "card_total": "Всего игр",
        "card_done": "Пройдено", "card_pct": "Завершение",
        "card_playing": "В процессе", "card_hours": "Наиграно часов",
        "card_avg": "Средняя оценка", "card_postponed": "Отложено",
        "card_dropped": "Брошено", "by_status": "По статусам",
        "card_verified": "Проверено Steam", "card_unverified": "Без проверки",
        "platforms": "Платформы", "genres": "Жанры", "genres_steam": "Жанры Steam",
        "genres_hint": "Жанры берутся из Steam, а не из ручного поля.",
        "no_data": "Нет данных. Добавьте игру из Steam — жанры подтянутся сами.",
        "verified_yes": "✓ Данные Steam подтверждены",
        "verified_wait": "Ожидание проверки Steam…",
        "verified_no": "Нет Steam AppID",
        "manual_note": "Ручные часы и оценка не идут в честную статистику.",
        "statusbar": "Всего: {total}  •  Хочу: {want}  •  В процессе: {playing}"
                     "  •  Пройдено: {done}  •  Показано: {shown}",
        "data_path": "v{}  •  данные: %APPDATA%\\GameBacklog",
        "tagline": "твой список игр, которые хочется пройти",
        "help_text": ("ДОБАВЛЕНИЕ\n  «＋ Steam» — поиск в каталоге Steam; если ничего нет,\n"
                      "  показываем топ чарт Steam.\n"
                      "  «＋ PC» — сканирование установленных игр.\n"
                      "  В окне выбора кликайте по карточкам — можно отметить несколько.\n\n"
                      "РЕДАКТИРОВАНИЕ\n  Клик по карточке открывает редактор справа.\n"
                      "  Меняйте статус, оценку, часы и заметки, затем «Сохранить».\n\n"
                      "СТАТИСТИКА\n  Жанры Steam проверяются через публичный API.\n"
                      "  Ручные часы и оценка в честные цифры не идут.\n\n"
                      "КАСТОМИЗАЦИЯ\n  «Настройки» в левом рейле — страница внутри окна:\n"
                       "  темы, цвета, шрифты, кнопки и вкладка game.\n\n"
                      "КОМПАКТНЫЙ РЕЖИМ\n  Вкладка «game» сворачивает окно.\n"
                       "  Край, положение и зеркало иконки — в Общих настройках.\n"
                      "  Правый клик — скрыть вкладку. Ctrl+Alt+G — вернуть окно.\n"
                       "  В «Общих» можно включить запуск вместе с Windows."),
        "set_title": "Настройки GameBacklog",
        "set_theme_tab": "Тема", "set_theme_hint": "Обери тему — зміниться вся палітра одразу.",
        "set_colors": "Цвета", "set_fonts": "Шрифты", "set_buttons": "Кнопки",
        "set_general": "Общее", "set_reset_colors": "Сбросить цвета",
        "set_family": "Шрифт", "set_size": "Размер", "set_title_size": "Размер заголовков",
        "set_add_font": "Добавить шрифт из файла…",
        "set_custom_fonts": "Добавленные шрифты:", "set_remove_font": "Убрать",
        "set_font_hint": "Поддерживаются .ttf и .otf. Шрифт появится в списке сразу.",
        "set_preview": "Предпросмотр: GameBacklog 123",
        "set_button_hint": "Тягни рядки мишкою, щоб змінити порядок. Клік по оку — показати/сховати. Стрілки теж працюють.",
        "set_preset_min": "Мінімум", "set_preset_normal": "Звичайно",
        "set_preset_all": "Всё", "set_reset_buttons": "Скинути",
        "set_live_hint": "Все изменения применяются сразу — кнопка «Применить» не нужна.",
        "set_up": "↑ Выше", "set_down": "↓ Ниже", "set_toggle": "Показать/скрыть",
        "set_theme": "Тема", "set_dark": "Тёмная", "set_light": "Светлая",
        "set_lang": "Язык", "set_dock_arrow": "Показывать вкладку «game»",
        "set_dock_edge": "Край кнопки game", "set_dock_position": "Положение по краю",
        "set_dock_mirror": "Зеркалить иконку", "set_dock_mirror_text": "Зеркалить текст",
        "set_autostart": "Запускать при включении компьютера",
        "dock_left": "Левый", "dock_right": "Правый",
        "dock_top": "Верхний", "dock_bottom": "Нижний",
        "apply": "Применить", "ok": "ОК", "cancel": "Отмена",
        "font_added": "Шрифт добавлен: {}", "font_error": "Не удалось добавить шрифт:\n{}",
        "dock_hide": "Скрыть вкладку", "dock_show": "Показать вкладку",
        "dock_restore": "Развернуть окно", "dock_exit": "Выйти",
    },
    "en": {
        "app_title": "GameBacklog — games I want to play",
        "app_name": "GameBacklog",
        "tab_list": "My games", "tab_stats": "Statistics",
        "edit": "✎ Edit", "delete": "⌫ Delete",
        "import": "↧ Import", "export": "↥ Export",
        "theme": "◐ Theme", "language": "文 RU/EN",
        "compact": "⇥ Collapse", "help": "? Help", "settings": "⚙ Settings",
        "library_eyebrow": "LIBRARY  ·  {}",
        "picker_selected": "Selected: {}", "picker_add": "＋ Add",
        "hint": "Click a game card — the editor opens on the right. "
                "Add games from Steam or from your PC.",
        "empty_list": "No games yet. Click «＋ Steam» or «＋ PC».",
        "search": "Search:", "status": "Status:", "platform": "Platform:",
        "active_only": "Active only", "sorting": "Sort:", "all": "All",
        "editor_header": "Game editor", "editor_hint": "Select a card on the left",
        "section_main": "Basic", "section_meta": "Rating and time",
        "section_links": "Link and tags", "section_dates": "Dates and notes",
        "section_status": "Status", "section_launch": "Launch",
        "section_notes": "Notes",
        "f_title": "Title", "f_platform": "Platform", "f_genre": "Genre",
        "f_status": "Status", "f_score": "Rating (0–10)", "f_hours": "Hours",
        "f_price": "Price, ₴", "f_link": "Link", "f_tags": "Tags (comma separated)",
        "f_added": "Added", "f_completed": "Completion date", "f_notes": "Notes",
        "save_changes": "✓ Save", "mark_done": "✓ Completed",
        "close_editor": "Close editor", "launch": "▶ Launch",
        "launch_ok": "Launched: {}", "launch_fail": "Could not launch: {}",
        "f_exe": ".exe path", "browse": "Browse…",
        "add_status": "+ Custom status", "status_name": "Status name",
        "status_exists": "This status already exists.",
        "status_rename": "Rename status", "status_delete": "Delete status",
        "status_delete_confirm": "Delete status «{}»? Its games will move to «Want to play».",
        "status_color": "Status color", "icon_update": "Refresh icon",
        "icon_done": "Icon downloaded.", "icon_fail": "Could not download icon: {}",
        "msg_select": "Please select a game first.",
        "delete_title": "Delete", "delete_confirm": "Delete «{}» from the list?",
        "delete_action": "Delete", "delete_warn": "This cannot be undone.",
        "steam_add": "＋ Steam", "steam_title": "Add a game from Steam",
        "steam_hint": "Type a name — games load from the Steam catalog.",
        "steam_note": "Steam catalog", "steam_search": "Search:",
        "steam_col_name": "Title", "steam_col_id": "AppID", "steam_col_price": "Price",
        "steam_add_btn": "＋ Add", "steam_close": "Close",
        "steam_wait": "Searching…", "steam_ready": "Found: {}", "steam_nothing": "Nothing found",
        "steam_top": "Nothing found — showing Steam top sellers",
        "steam_error": "Could not load Steam data: {}",
        "steam_select": "Select a game in the results first.",
        "steam_details": "Loading genres and covers…",
        "steam_added": "Added from Steam: {}\nSkipped (already present): {}",
        "steam_free": "free",
        "pc_add": "＋ PC", "pc_title": "Games on this PC",
        "pc_hint": "Detected installed games — select and add them.",
        "pc_scan": "Scan", "pc_browse": "Choose folder",
        "pc_scanning": "Scanning…", "pc_found": "Found: {}",
        "pc_source": "Source", "pc_path": "Path",
        "pc_added": "Added: {}\nSkipped: {}",
        "pc_empty": "No games found. Install Steam/Epic or choose a games folder.",
        "pc_select": "Select a game in the list first.",
        "export_title": "Export game list", "import_title": "Import game list",
        "import_prompt": ("Games found: {}\n\nYES — replace the current list.\n"
                          "NO — merge into current list (duplicates skipped)."),
        "import_done": "Import complete. Games in list: {}",
        "export_done": "Exported to:\n{}",
        "import_error": "Import error:\n{}", "export_error": "Export error:\n{}",
        "saved": "Saved.", "load_error": "Could not read the data file:\n{}",
        "save_error": "Could not save data:\n{}",
        "empty_export": "The list is empty — nothing to export.",
        "stats_header": "Your backlog statistics", "card_total": "Total games",
        "card_done": "Completed", "card_pct": "Completion",
        "card_playing": "Playing", "card_hours": "Hours played",
        "card_avg": "Average rating", "card_postponed": "Postponed",
        "card_dropped": "Dropped", "by_status": "By status",
        "card_verified": "Steam verified", "card_unverified": "Unverified",
        "platforms": "Platforms", "genres": "Genres", "genres_steam": "Steam genres",
        "genres_hint": "Genres come from Steam, not from the manual field.",
        "no_data": "No data. Add a Steam game — genres load automatically.",
        "verified_yes": "✓ Steam data verified",
        "verified_wait": "Waiting for Steam check…",
        "verified_no": "No Steam AppID",
        "manual_note": "Manual hours and score are excluded from honest stats.",
        "statusbar": "Total: {total}  •  Want: {want}  •  Playing: {playing}"
                     "  •  Done: {done}  •  Shown: {shown}",
        "data_path": "v{}  •  data: %APPDATA%\\GameBacklog",
        "tagline": "your list of games you want to play",
        "help_text": ("ADDING\n  «＋ Steam» searches the Steam catalog; if nothing is found,\n"
                      "  Steam top sellers are shown instead.\n"
                      "  «＋ PC» scans games installed on your computer.\n"
                      "  In the picker, click cards to toggle — multiple games are allowed.\n\n"
                      "EDITING\n  Click a game card to open the editor on the right.\n"
                      "  Change status, rating, hours and notes, then press Save.\n\n"
                      "STATS\n  Steam genres are verified through the public API.\n"
                      "  Manual hours and score are excluded from honest numbers.\n\n"
                      "CUSTOMIZATION\n  «Settings» in the left rail is a page inside the window:\n"
                       "  themes, colors, fonts, buttons and the game tab.\n\n"
                      "COMPACT MODE\n  The «game» tab collapses the window.\n"
                       "  Edge, position and icon mirror are in General settings.\n"
                      "  Right-click hides it. Ctrl+Alt+G restores the window.\n"
                       "  General settings can start the app with Windows."),
        "set_title": "GameBacklog Settings",
        "set_theme_tab": "Theme", "set_theme_hint": "Pick a theme — the whole palette changes at once.",
        "set_colors": "Colors", "set_fonts": "Fonts", "set_buttons": "Buttons",
        "set_general": "General", "set_reset_colors": "Reset colors",
        "set_family": "Font", "set_size": "Size", "set_title_size": "Title size",
        "set_add_font": "Add font from file…",
        "set_custom_fonts": "Added fonts:", "set_remove_font": "Remove",
        "set_font_hint": ".ttf and .otf supported. The font appears in the list at once.",
        "set_preview": "Preview: GameBacklog 123",
        "set_button_hint": "Drag rows to reorder. Click the eye to show/hide. Arrows work too.",
        "set_preset_min": "Minimal", "set_preset_normal": "Normal",
        "set_preset_all": "All", "set_reset_buttons": "Reset",
        "set_live_hint": "Changes apply instantly — no Apply button needed.",
        "set_up": "↑ Up", "set_down": "↓ Down", "set_toggle": "Show/hide",
        "set_theme": "Theme", "set_dark": "Dark", "set_light": "Light",
        "set_lang": "Language", "set_dock_arrow": "Show the «game» tab",
        "set_dock_edge": "Game button edge", "set_dock_position": "Position along edge",
        "set_dock_mirror": "Mirror icon", "set_dock_mirror_text": "Mirror text",
        "set_autostart": "Start with Windows",
        "dock_left": "Left", "dock_right": "Right",
        "dock_top": "Top", "dock_bottom": "Bottom",
        "apply": "Apply", "ok": "OK", "cancel": "Cancel",
        "font_added": "Font added: {}", "font_error": "Could not add font:\n{}",
        "dock_hide": "Hide tab", "dock_show": "Show tab",
        "dock_restore": "Restore window", "dock_exit": "Exit",
    },
}


# --------------------------------------------------------------------------- утиліти
def make_game(title: str = "") -> dict[str, Any]:
    return {"id": uuid.uuid4().hex, "title": title.strip(), "platform": "PC",
            "genre": "", "status": "want", "score": "", "hours": "", "price": "",
            "link": "", "tags": "", "added": date.today().isoformat(),
            "completed": "", "notes": "", "order": 0,
            "appid": "", "exe": "", "icon": "",
            "steam_verified": False, "verified_genres": [], "verified_at": ""}


def normalize_game(raw: dict[str, Any], custom_keys: set[str] | None = None) -> dict[str, Any]:
    game = make_game(str(raw.get("title", "")))
    for key in FIELDS:
        if key in raw and raw[key] is not None:
            game[key] = raw[key]
    game["id"] = str(game["id"]) or uuid.uuid4().hex
    game["title"] = str(game["title"]).strip()
    status = str(game["status"])
    valid = set(STATUSES) | (custom_keys or set())
    game["status"] = STATUS_ALIASES.get(status, status if status in valid else "want")
    try:
        game["order"] = int(float(game["order"]))
    except (TypeError, ValueError):
        game["order"] = 0
    flag = game.get("steam_verified", False)
    game["steam_verified"] = (flag is True or
                              str(flag).strip().lower() in ("1", "true", "yes"))
    raw_genres = game.get("verified_genres") or []
    if isinstance(raw_genres, str):
        raw_genres = raw_genres.split(",")
    game["verified_genres"] = [str(g).strip() for g in raw_genres
                               if str(g).strip()]
    game["verified_at"] = str(game.get("verified_at") or "")
    return game


def read_settings() -> dict[str, Any]:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict[str, Any]) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_data(locale: str = "ru") -> list[dict[str, Any]]:
    custom_keys = {str(s.get("key", "")) for s in custom_statuses(read_settings())}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return [normalize_game(item, custom_keys)
                    for item in data if isinstance(item, dict)]
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError):
        pass
    return []


def save_data(games: list[dict[str, Any]], locale: str = "ru") -> bool:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as fh:
            json.dump(games, fh, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def as_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return 0.0


def is_steam_verified(game: dict[str, Any]) -> bool:
    """Гра має AppID і хоч раз отримувала дані з публічного Steam API."""
    return (bool(game.get("steam_verified")) and
            str(game.get("appid") or "").strip().isdigit())


def steam_verified_genres(game: dict[str, Any]) -> list[str]:
    """Жанри, які прийшли з Steam, а не з ручного поля редактора."""
    raw = game.get("verified_genres") or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(g).strip() for g in raw if str(g).strip()]


def mark_steam_verified(game: dict[str, Any], genres: list[str] | tuple[str, ...],
                        appid: int | str = "") -> None:
    """Позначаємо гру як перевірену Steam і зберігаємо її жанри."""
    if str(appid).strip().isdigit():
        game["appid"] = str(appid).strip()
    game["steam_verified"] = bool(str(game.get("appid") or "").strip().isdigit())
    game["verified_genres"] = [str(g).strip() for g in (genres or []) if str(g).strip()]
    game["verified_at"] = date.today().isoformat() if game["steam_verified"] else ""


def mix(color1: str, color2: str, t: float) -> str:
    try:
        a = [int(color1[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(color2[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))
    except (ValueError, IndexError):
        return color1


def text_on(color: str) -> str:
    try:
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        return "#0b1020" if (r * 299 + g * 587 + b * 114) / 1000 > 150 else "#ffffff"
    except (ValueError, IndexError):
        return "#ffffff"


def initials(title: str) -> str:
    words = [w for w in re.split(r"[\s:–—-]+", str(title).strip()) if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def load_custom_fonts(paths: list[str]) -> None:
    if os.name != "nt" or not paths:
        return
    try:
        import ctypes
        gdi, user = ctypes.windll.gdi32, ctypes.windll.user32
        gdi.AddFontResourceW.argtypes = [ctypes.c_wchar_p]
        gdi.AddFontResourceW.restype = ctypes.c_int
        if any(os.path.isfile(p) and gdi.AddFontResourceW(p) for p in paths):
            user.SendMessageW(0xFFFF, 0x001D, 0, 0)
    except Exception:
        pass


# --------------------------------------------------------------------------- Steam API
def steam_search(term: str, free_label: str = "free") -> list[tuple[str, int, str]]:
    url = ("https://store.steampowered.com/api/storesearch/?"
           + urllib.parse.urlencode({"term": term, "l": "english", "cc": "us"}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.load(resp)
    items = []
    for item in data.get("items", []):
        if item.get("type") != "app":
            continue
        price = item.get("price") or {}
        final = price.get("final")
        text = free_label if final is None else (
            f"{final / 100:.2f} {price.get('currency', '')}".strip())
        items.append((str(item.get("name", "")), int(item["id"]), text))
    return items


def steam_top_charts(limit: int = 10, free_label: str = "free") -> list[dict[str, str]]:
    """Топ чарт Steam без ключів: публічний endpoint featuredcategories."""
    url = "https://store.steampowered.com/api/featuredcategories/?cc=us&l=english"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        payload = json.load(resp)
    skip = {"steam machine", "steam frame", "steam deck", "steam controller"}
    items: list[dict[str, str]] = []
    seen: set[int] = set()
    for entry in (payload.get("top_sellers") or {}).get("items", []):
        try:
            appid = int(entry.get("id") or 0)
        except (TypeError, ValueError):
            continue
        name = str(entry.get("name") or "").strip()
        if not appid or not name or appid in seen or name.lower() in skip:
            continue
        seen.add(appid)
        final = entry.get("final_price")
        price = free_label if final is None else (
            f"{final / 100:.2f} {entry.get('currency', '')}".strip())
        items.append({"name": name, "appid": str(appid), "price": price,
                      "icon_url": str(entry.get("header_image") or "")})
        if len(items) >= limit:
            break
    return items


def steam_appdata(appid: int | str) -> dict[str, Any]:
    """Публічні дані Steam appdetails — жанри й справжня обкладинка."""
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.load(resp)
        entry = payload.get(str(appid), {})
        if entry.get("success"):
            return entry.get("data", {})
    except Exception:
        pass
    return {}


def steam_genres(appid: int) -> list[str]:
    data = steam_appdata(appid)
    return [g["description"] for g in data.get("genres", []) if g.get("description")]


def steam_header_url(appid: int | str) -> str:
    data = steam_appdata(appid)
    header = str(data.get("header_image") or "")
    return header or f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"


def cache_steam_icon(appid: int | str, url: str = "") -> str:
    """Завантажує header.jpg у %APPDATA%\\GameBacklog\\icons і повертає шлях."""
    try:
        os.makedirs(ICONS_DIR, exist_ok=True)
        target = os.path.join(ICONS_DIR, f"{appid}.jpg")
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            return target
        req = urllib.request.Request(url or steam_header_url(appid),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp, open(target, "wb") as fh:
            fh.write(resp.read())
        return target if os.path.getsize(target) > 0 else ""
    except Exception:
        return ""


def steam_game_info(appid: int | str) -> tuple[list[str], str]:
    """Жанри + локальний шлях до оригінальної обкладинки Steam."""
    data = steam_appdata(appid)
    genres = [g["description"] for g in data.get("genres", []) if g.get("description")]
    header = str(data.get("header_image") or "")
    icon = cache_steam_icon(appid, header) if header else ""
    return genres, icon


def appid_from_link(link: str) -> str:
    found = re.search(r"(?:app/|rungameid/)(\d+)", str(link or ""))
    return found.group(1) if found else ""


def launch_game(game: dict[str, Any]) -> tuple[bool, str]:
    """Запускає Steam-гру або локальний .exe. Повертає (успіх, опис)."""
    appid = str(game.get("appid") or "") or appid_from_link(game.get("link", ""))
    if appid:
        webbrowser.open(f"steam://rungameid/{appid}")
        return True, "Steam"
    exe = str(game.get("exe") or "").strip().strip('"')
    if not exe:
        match = re.search(r"(?:Путь|Path):\s*(.+)$", str(game.get("notes") or ""),
                          re.IGNORECASE | re.MULTILINE)
        exe = match.group(1).strip() if match else ""
    if exe and os.path.isfile(exe):
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True)
            return True, exe
        except OSError as exc:
            return False, str(exc)
    return False, "Steam AppID / .exe not found"


# --------------------------------------------------------------------------- сканери
def steam_roots() -> list[str]:
    roots = []
    if winreg:
        for hive, path in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                           (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, path) as key:
                    value = winreg.QueryValueEx(key, "SteamPath")[0]
                    if value and os.path.isdir(value) and value not in roots:
                        roots.append(value)
            except OSError:
                pass
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            path = os.path.join(base, "Steam")
            if os.path.isdir(path) and path not in roots:
                roots.append(path)
    return roots


def scan_steam() -> list[dict[str, str]]:
    found, libraries = [], []
    for root in steam_roots():
        libraries.append(root)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            try:
                with open(vdf, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
                for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                    path = match.group(1).replace("\\\\", "\\")
                    if os.path.isdir(path) and path not in libraries:
                        libraries.append(path)
            except OSError:
                pass
    seen = set()
    for library in libraries:
        steamapps = os.path.join(library, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        try:
            files = os.listdir(steamapps)
        except OSError:
            continue
        for filename in files:
            if not filename.startswith("appmanifest_") or not filename.endswith(".acf"):
                continue
            try:
                with open(os.path.join(steamapps, filename), "r",
                          encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
                appid = re.search(r'"appid"\s+"(\d+)"', text)
                name = re.search(r'"name"\s+"([^"]+)"', text)
                if not (appid and name):
                    continue
                key = ("Steam", appid.group(1))
                if key in seen:
                    continue
                seen.add(key)
                found.append({"name": name.group(1), "appid": appid.group(1),
                              "source": "Steam",
                              "path": os.path.join(steamapps, "common", name.group(1))})
            except OSError:
                pass
    return found


def scan_epic() -> list[dict[str, str]]:
    found = []
    base = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                        "Epic", "EpicGamesLauncher", "Data", "Manifests")
    if not os.path.isdir(base):
        return found
    for filename in os.listdir(base):
        if not filename.endswith(".item"):
            continue
        try:
            with open(os.path.join(base, filename), "r",
                      encoding="utf-8", errors="ignore") as fh:
                data = json.load(fh)
            name = data.get("DisplayName") or data.get("AppName")
            if name:
                found.append({"name": str(name), "appid": "", "source": "Epic",
                              "path": str(data.get("InstallLocation", ""))})
        except (OSError, json.JSONDecodeError):
            pass
    return found


def scan_uninstall() -> list[dict[str, str]]:
    found = []
    if not winreg:
        return found
    marks = ("steamapps", "epic games", "gog galaxy", "gog.com", "xboxgames", "ubisoft")
    bases = [r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"]
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for base in bases:
            try:
                with winreg.OpenKey(hive, base) as root:
                    index = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(root, index)
                            index += 1
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(root, sub) as key:
                                def value(name):
                                    try:
                                        return str(winreg.QueryValueEx(key, name)[0])
                                    except OSError:
                                        return ""

                                name, location, publisher = (
                                    value("DisplayName"), value("InstallLocation"),
                                    value("Publisher"))
                                blob = f"{location} {publisher}".lower()
                                if not name or not any(m in blob for m in marks):
                                    continue
                                source = ("GOG" if "gog" in blob else
                                          "Xbox" if "xbox" in blob else
                                          "Ubisoft" if "ubisoft" in blob else "Steam")
                                found.append({"name": name, "appid": "",
                                              "source": source, "path": location})
                        except OSError:
                            pass
            except OSError:
                pass
    return found


def find_game_exe(path: str) -> str:
    """Грамотний/main .exe з папки гри; ключові оновлювачі пропускаємо."""
    path = str(path or "").strip().strip('"')
    if not path:
        return ""
    if os.path.isfile(path) and path.lower().endswith(".exe"):
        return path
    if not os.path.isdir(path):
        return ""
    skip = ("unins", "setup", "update", "crash", "redist", "vcredist",
            "dxwebsetup", "dotnet", "directx", "activation")
    candidates = []
    for name in os.listdir(path):
        low = name.lower()
        if not low.endswith(".exe") or any(part in low for part in skip):
            continue
        candidates.append(os.path.join(path, name))
    if not candidates:
        return ""
    return sorted(candidates, key=lambda item: (len(os.path.basename(item)), item.lower()))[0]


def scan_installed() -> list[dict[str, str]]:
    items = scan_steam() + scan_epic() + scan_uninstall()
    unique = {}
    for item in items:
        unique.setdefault(item["name"].strip().lower(), item)
    return list(unique.values())


def read_export(path: str) -> list[dict[str, Any]]:
    if path.lower().endswith(".csv"):
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else []


def write_export(path: str, games: list[dict[str, Any]]) -> None:
    if path.lower().endswith(".csv"):
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(games)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(games, fh, ensure_ascii=False, indent=2)
