"""Platform-agnostic keyboard builders (for MAX and future platforms)."""
from src.platforms.base import Button, ButtonType, KeyboardRow


def get_main_menu_rows() -> list[KeyboardRow]:
    return [
        [Button("🚨 SOS", payload="menu_sos")],
        [Button("🏍 Мотопара", payload="menu_motopair")],
        [Button("📇 Полезные контакты", payload="menu_contacts")],
        [Button("📅 Мероприятия", payload="menu_events")],
        [Button("👤 Мой профиль", payload="menu_profile")],
        [Button("ℹ️ О нас", payload="menu_about")],
    ]


def get_city_select_rows() -> list[KeyboardRow]:
    return [[Button("Екатеринбург", payload="city_ekb")]]


def get_role_select_rows() -> list[KeyboardRow]:
    return [
        [
            Button("Я Пилот", payload="role_pilot"),
            Button("Я Двойка", payload="role_passenger"),
        ],
    ]


def get_back_to_menu_rows() -> list[KeyboardRow]:
    return [[Button("« Назад в меню", payload="menu_main")]]


def get_contact_button_row() -> KeyboardRow:
    return [Button("Отправить мой номер", type=ButtonType.REQUEST_CONTACT)]


def get_location_button_row() -> KeyboardRow:
    return [Button("Отправить геолокацию", type=ButtonType.REQUEST_LOCATION)]
