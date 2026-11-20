"""Language-independent unit tests for the Russian follow-up parser."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parent.parent / "custom_components" / "fiendishly_reminders" / "voice_ru.py"
spec = importlib.util.spec_from_file_location("voice_ru", SRC)
ru = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ru)
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)

class RussianVoiceTests(unittest.TestCase):
    def check(self, phrase, expected, rule=None):
        _, due, recurrence = ru.read_time(phrase, NOW)
        self.assertIsNotNone(due, phrase)
        self.assertEqual((due.year, due.month, due.day, due.hour, due.minute, due.second), expected, phrase)
        self.assertEqual(recurrence, rule, phrase)

    def test_numbers(self):
        for phrase, n in (("десять", 10), ("двадцать пять", 25),
                          ("сто двадцать один", 121), ("42", 42), ("две", 2)):
            self.assertEqual(ru.number(phrase), n)
        for phrase in ("пять двадцать", "сколько-нибудь", "пятнадцать пять"):
            self.assertIsNone(ru.number(phrase))

    def test_relative(self):
        self.check("через двадцать минут", (2026,11,18,9,20,0))
        self.check("через полчаса", (2026,11,18,9,30,0))
        self.check("через полтора часа", (2026,11,18,10,30,0))
        self.check("через полторы минуты", (2026,11,18,9,1,30))

    def test_compound_relative(self):
        _, due, _ = ru.read_time("покормить малыша через четыре часа тридцать минут", NOW)
        self.assertEqual(due - NOW, timedelta(hours=4, minutes=30))
        _, due, _ = ru.read_time("через час и двадцать пять минут десять секунд", NOW)
        self.assertEqual(due - NOW, timedelta(hours=1, minutes=25, seconds=10))
        _, due, _ = ru.read_time("через два часа и три часа", NOW)
        self.assertIsNone(due)

    def test_cardinal_plus_fraction(self):
        self.check("через четыре с половиной часа",
                   (2026,11,18,13,30,0))
        self.check("спустя пять с половиной минут",
                   (2026,11,18,9,5,30))
        self.check("через два часа с половиной",
                   (2026,11,18,11,30,0))
        self.check("через три с четвертью часа",
                   (2026,11,18,12,15,0))
        self.check("через четыре с тремя четвертями часа",
                   (2026,11,18,13,45,0))
        self.check("через 4 с половиной часа",
                   (2026,11,18,13,30,0))
        self.check("через двадцать четыре с половиной часа",
                   (2026,11,19,9,30,0))
        self.assertIsNone(ru.read_time("через сколько-то с половиной часа", NOW)[1])

    def test_clock_and_day(self):
        self.check("завтра в девять вечера", (2026,11,19,21,0,0))
        self.check("послезавтра в 10:30", (2026,11,20,10,30,0))
        self.check("в двадцать один час", (2026,11,18,21,0,0))
        self.check("завтра утром", (2026,11,19,8,15,0))
        self.check("в восемь часов тридцать минут", (2026,11,19,8,30,0))

    def test_weekly(self):
        self.check("каждый вторник в девять утра", (2026,11,24,9,0,0), "FREQ=WEEKLY;BYDAY=TU")

    def test_unknown_does_not_schedule(self):
        for text in ("позже", "всё равно", "завтра примерно когда-нибудь"):
            _, due, recurrence = ru.read_time(text, NOW)
            if text != "завтра примерно когда-нибудь":
                self.assertIsNone(due)
                self.assertIsNone(recurrence)

    def test_confirmations_and_messages(self):
        self.assertFalse(set(ru.YES_SENTENCES) & set(ru.NO_SENTENCES))
        self.assertEqual(ru.message("created", text="проверить духовку",
                                    when="18.11.2026 в 21:00"),
                         "Напоминание «проверить духовку» установлено на 18.11.2026 в 21:00.")
        self.assertIn("Отменено", ru.message("cancel_many", count=3))
        self.assertIn("Напоминание", ru.delivery_header())
        self.assertIn("Иван", ru.delivery_header("Иван"))
        self.assertEqual(ru.clock(NOW), "09:00")

    def test_edit(self):
        self.assertEqual(ru.parse_edit_answer("измени название на купить молоко", NOW),
                         ("купить молоко", None, None))
        text, due, rrule = ru.parse_edit_answer("перенеси на завтра в девять вечера", NOW)
        self.assertIsNone(text)
        self.assertEqual((due.day,due.hour), (19,21))
        self.assertIsNone(rrule)

if __name__ == "__main__":
    unittest.main()
