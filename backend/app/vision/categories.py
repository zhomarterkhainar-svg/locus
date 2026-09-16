"""Категории профиля и текстовые промпты для zero-shot классификации CLIP."""
from __future__ import annotations

CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "campus": ("Кампус и корпуса", [
        "a photo of a university main building exterior",
        "a photo of a modern university building with glass facade",
        "a photo of university buildings on a campus with lawns and paths",
        "a photo of a college building facade with the university name",
        "an aerial photo of a university campus",
        "a photo of a large atrium or lobby inside a university",
    ]),
    "dormitory": ("Общежития", [
        "a photo of a student dormitory room with beds",
        "a photo of a student dormitory building exterior",
        "a photo of a shared kitchen in a student dormitory",
        "a photo of a small hostel room with beds and desks",
        "a photo of a dormitory corridor",
    ]),
    "classroom": ("Аудитории", [
        "a photo of a tiered lecture hall with rows of seats facing a board",
        "a photo of a classroom with student desks facing a blackboard or whiteboard",
        "a photo of an empty university auditorium with a projector screen",
        "a photo of a computer classroom with monitors on desks",
    ]),
    "library": ("Библиотеки", [
        "a photo of a library reading room",
        "a photo of bookshelves in a university library",
        "a photo of students studying at tables in a library",
    ]),
    "lab": ("Лаборатории", [
        "a photo of a science laboratory with equipment",
        "a photo of a chemistry laboratory with glassware",
        "a photo of students in lab coats working in a laboratory",
        "a photo of an engineering or robotics lab",
    ]),
    "sport": ("Спорт", [
        "a photo of an indoor sports hall",
        "a photo of an indoor swimming pool",
        "a photo of a stadium or a football field",
        "a photo of a fitness gym with exercise machines",
        "a photo of a basketball or volleyball court",
    ]),
    "canteen": ("Столовые и кафе", [
        "a photo of a cafeteria with a food counter and trays",
        "a photo of people eating in a canteen dining hall",
        "a photo of a student cafe with food and drinks",
    ]),
    "student_life": ("Студенческая жизнь", [
        "a photo of students at a university event",
        "a photo of a student concert or festival",
        "a photo of a group of students on campus",
        "a photo of a conference with an audience",
        "a photo of a graduation ceremony with graduates",
        "a photo of an official ceremony with people shaking hands",
    ]),
    "city": ("Город", [
        "a photo of a city street with cars and pedestrians",
        "a photo of a city skyline",
        "a photo of a famous city landmark, monument or mosque",
        "a photo of a public square or park in a city",
        "a photo of a winter street in a city",
    ]),
}

TRASH: dict[str, tuple[str, list[str]]] = {
    "logo": ("логотип или эмблема", ["a logo", "an emblem or a coat of arms", "an icon on a plain background"]),
    "text": ("изображение с текстом, афиша или документ", ["a poster with text", "a banner with large text", "a screenshot of a document", "an infographic", "a certificate or a diploma"]),
    "portrait": ("портрет человека", ["a close-up portrait photo of one person", "a headshot of a person in a suit", "an official photo of a politician"]),
    "map": ("карта или схема", ["a map", "a floor plan or a diagram", "a chart with numbers"]),
    "stamp": ("марка, монета или купюра", ["a postage stamp", "a coin or a banknote"]),
    "other": ("не по теме", ["a photo of food on a plate", "a photo of a car", "a cartoon or an illustration", "a 3D render of a building", "a photo of a product on a white background"]),
}

WATERMARK_PROMPTS = ["a stock photo with a watermark across it", "an image with a semi-transparent watermark logo"]

SUB_PROMPTS: dict[str, list[str]] = {
    "dorm_room": ["a photo of a bedroom with beds in a dormitory", "a photo of a hostel room with bunk beds"],
    "dorm_kitchen": ["a photo of a shared kitchen with stoves", "a photo of a kitchen with a refrigerator and sink"],
    "dorm_bathroom": ["a photo of a shower room", "a photo of a bathroom with a sink and toilet"],
    "dorm_exterior": ["a photo of a residential building exterior"],
    "dorm_corridor": ["a photo of a long corridor with doors"],
    "sport_gym": ["a photo of a fitness gym with exercise machines and weights"],
    "sport_pool": ["a photo of an indoor swimming pool with lanes"],
    "sport_stadium": ["a photo of a stadium with a running track or a football field"],
    "sport_court": ["a photo of an indoor sports hall with a basketball or volleyball court"],
}

# Второй этап для вырезок кроватей: двухъярусная или обычная
BUNK_PROMPTS: dict[str, list[str]] = {
    "bunk_bed": ["a photo of a bunk bed", "a two-tier bunk bed with a ladder", "a metal double-decker bed in a dormitory"],
    "single_bed": ["a photo of a single bed", "a single bed with a mattress and a blanket", "a low single bed next to a wall"],
}

SHELF_PREFIX = {
    "campus": "КАМ", "dormitory": "ОБЩ", "classroom": "АУД", "library": "БИБ", "lab": "ЛАБ",
    "sport": "СПТ", "canteen": "СТЛ", "student_life": "СТЖ", "city": "ГОР",
}

# Для фото, найденных вокруг центра города, внутренние помещения не подходят
CITY_ALLOWED = {"city", "campus"}
