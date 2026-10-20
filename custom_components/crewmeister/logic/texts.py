"""Texts of notifications sent by the assistant (German and English)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

TEXTS: dict[str, dict[str, str]] = {
    "de": {
        # Buttons
        "btn_clock_in": "Einstempeln",
        "btn_clock_in_at": "Einstempeln ({time})",
        "btn_clock_out": "Ausstempeln",
        "btn_clock_out_at": "Ausstempeln ({time})",
        "btn_break": "Pause",
        "btn_break_at": "Pause ab {time}",
        "btn_resume": "Weiterarbeiten",
        "btn_snooze": "In {minutes} min erinnern",
        "btn_ignore": "Ignorieren",
        "btn_clock_out_now": "Jetzt ausstempeln",
        "btn_add_break": "{minutes} min Pause nachtragen",
        # Arrival / departure
        "arrived_title": "Bei der Arbeit angekommen",
        "arrived_message": "Du bist seit {time} da. Jetzt einstempeln?",
        "returned_title": "Zurück aus der Pause?",
        "returned_message": "Du bist seit {time} wieder da. Pause beenden?",
        "short_leave_message": "Pause von {start} bis {end} gestempelt.",
        "left_title": "Arbeitsort verlassen",
        "left_message": "Du bist um {time} gegangen und noch eingestempelt.",
        "home_office_title": "Homeoffice erkannt",
        "home_office_message": "Du arbeitest seit {time} zu Hause. Jetzt einstempeln?",
        "home_office_idle_title": "Keine Aktivität mehr",
        "home_office_idle_message": "Seit {time} keine Aktivität am Arbeitsplatz zu Hause, du bist noch eingestempelt.",
        "location_office": "Büro",
        "location_home_office": "Homeoffice",
        # Reminders
        "still_clocked_in_title": "Noch eingestempelt",
        "still_clocked_in_message": "Du arbeitest heute schon {worked}. Ausstempeln nicht vergessen!",
        "max_work_title": "Höchstarbeitszeit erreicht",
        "max_work_message": "Du arbeitest heute schon {worked}. Zeit für den Feierabend.",
        "end_of_day_title": "Feierabend?",
        "end_of_day_message": "Deine Soll-Arbeitszeit von {target} war um {time} erreicht. Ausstempeln?",
        "forgotten_title": "Ausstempeln vergessen?",
        "forgotten_message": "Du bist seit {start} eingestempelt.",
        "forgotten_message_left": "Du bist seit {start} eingestempelt und hast um {left} den Arbeitsort verlassen.",
        # Breaks
        "break_due_title": "Zeit für eine Pause",
        "break_due_message": "Du arbeitest seit {worked} ohne Pause.",
        "break_over_title": "Pause vorbei",
        "break_over_message": "Deine Pause läuft seit {duration}.",
        "break_missing_title": "Pause zu kurz",
        "break_missing_message": "Bei {worked} Arbeitszeit sind {required} Pause vorgeschrieben, du hattest {taken} (gezählt werden Pausen ab 15 min).",
        "lunch_title": "Mittagspause",
        "lunch_message": "Pause automatisch gestartet.",
        # Confirmations and status
        "stamped_START_WORK": "Eingestempelt um {time}",
        "stamped_START_BREAK": "Pause seit {time}",
        "stamped_CLOCK_OUT": "Ausgestempelt um {time} – heute {worked}, Pause {breaks}",
        "break_added": "{minutes} min Pause nachgetragen",
        "stamp_failed_title": "Stempeln fehlgeschlagen",
        "error_already_clocked_in": "Du bist bereits eingestempelt.",
        "error_no_shift_to_pause": "Es läuft keine Arbeitszeit, die pausiert werden kann.",
        "error_no_shift_to_clock_out": "Du bist nicht eingestempelt.",
        "error_outdated": "Die Aktion ist veraltet, seitdem wurde bereits neu gestempelt.",
        "error_unavailable": "Crewmeister ist gerade nicht erreichbar.",
        "error_api": "{error}",
        "status_title": "Crewmeister",
        "options_notify_hint": "⚠️ Unter „Benachrichtigungen“ ist noch kein Handy ausgewählt. Nachfragen und Erinnerungen werden erst zugestellt, wenn eines ausgewählt ist.\n\n",
        "status_clocked_in": "Eingestempelt seit {time}",
        "status_on_break": "Pause seit {time}",
        "live_work": "🔵 Arbeit seit {start}",
        "live_breaks": "🟡 Pause {breaks}",
        "live_break": "🟡 Pause seit {since}",
        "live_worked": "🔵 Arbeit heute {worked}",
        "live_end": "Feierabend ca. {end}",
        "live_critical_work": "Arbeit",
        "live_critical_break": "Pause",
    },
    "en": {
        "btn_clock_in": "Clock in",
        "btn_clock_in_at": "Clock in ({time})",
        "btn_clock_out": "Clock out",
        "btn_clock_out_at": "Clock out ({time})",
        "btn_break": "Break",
        "btn_break_at": "Break from {time}",
        "btn_resume": "Resume work",
        "btn_snooze": "Remind in {minutes} min",
        "btn_ignore": "Ignore",
        "btn_clock_out_now": "Clock out now",
        "btn_add_break": "Add {minutes} min break",
        "arrived_title": "Arrived at work",
        "arrived_message": "You have been here since {time}. Clock in now?",
        "returned_title": "Back from your break?",
        "returned_message": "You are back since {time}. End the break?",
        "short_leave_message": "Stamped a break from {start} to {end}.",
        "left_title": "Left work",
        "left_message": "You left at {time} and are still clocked in.",
        "home_office_title": "Working from home detected",
        "home_office_message": "You have been working from home since {time}. Clock in now?",
        "home_office_idle_title": "No more activity",
        "home_office_idle_message": "No activity at your desk at home since {time}, you are still clocked in.",
        "location_office": "Office",
        "location_home_office": "Home office",
        "still_clocked_in_title": "Still clocked in",
        "still_clocked_in_message": "You have worked {worked} today. Don't forget to clock out!",
        "max_work_title": "Maximum working time reached",
        "max_work_message": "You have worked {worked} today. Time to call it a day.",
        "end_of_day_title": "Time to go home?",
        "end_of_day_message": "Your target working time of {target} was reached at {time}. Clock out?",
        "forgotten_title": "Forgot to clock out?",
        "forgotten_message": "You have been clocked in since {start}.",
        "forgotten_message_left": "You have been clocked in since {start} and left work at {left}.",
        "break_due_title": "Time for a break",
        "break_due_message": "You have been working for {worked} without a break.",
        "break_over_title": "Break is over",
        "break_over_message": "Your break has lasted {duration}.",
        "break_missing_title": "Break too short",
        "break_missing_message": "{worked} of work require a {required} break, you took {taken} (only breaks of 15 min or more count).",
        "lunch_title": "Lunch break",
        "lunch_message": "Break started automatically.",
        "stamped_START_WORK": "Clocked in at {time}",
        "stamped_START_BREAK": "On break since {time}",
        "stamped_CLOCK_OUT": "Clocked out at {time} – {worked} today, break {breaks}",
        "break_added": "Added a {minutes} min break",
        "stamp_failed_title": "Stamping failed",
        "error_already_clocked_in": "You are already clocked in.",
        "error_no_shift_to_pause": "There is no running shift to pause.",
        "error_no_shift_to_clock_out": "You are not clocked in.",
        "error_outdated": "This action is outdated, a newer stamp exists.",
        "error_unavailable": "Crewmeister is currently unavailable.",
        "error_api": "{error}",
        "status_title": "Crewmeister",
        "options_notify_hint": "⚠️ No phone is selected under “Notifications” yet. Questions and reminders are only delivered once one is selected.\n\n",
        "status_clocked_in": "Clocked in since {time}",
        "status_on_break": "On break since {time}",
        "live_work": "🔵 Working since {start}",
        "live_breaks": "🟡 Break {breaks}",
        "live_break": "🟡 Break since {since}",
        "live_worked": "🔵 Worked {worked} today",
        "live_end": "done around {end}",
        "live_critical_work": "Work",
        "live_critical_break": "Break",
    },
}


def text(language: str | None, key: str, **placeholders: Any) -> str:
    """Return the text ``key`` in ``language`` (falling back to English)."""

    lang = (language or "en").split("-", 1)[0].lower()
    template = TEXTS.get(lang, TEXTS["en"]).get(key) or TEXTS["en"][key]
    return template.format(**placeholders)


def format_duration(value: timedelta) -> str:
    """Format a duration as ``H:MM h``."""

    minutes = max(0, int(value.total_seconds() // 60))
    return f"{minutes // 60}:{minutes % 60:02d} h"
