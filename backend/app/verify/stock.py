"""Стоковые фотобанки. Фото оттуда нельзя выдавать за конкретный кампус."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

STOCK_DOMAINS = {
    "shutterstock.com", "istockphoto.com", "gettyimages.com", "depositphotos.com", "dreamstime.com",
    "123rf.com", "alamy.com", "freepik.com", "pexels.com", "unsplash.com", "pixabay.com", "stock.adobe.com",
    "adobestock.com", "bigstockphoto.com", "canstockphoto.com", "vecteezy.com", "rawpixel.com",
    "photodune.net", "envato.com", "lori.ru", "fotolia.com", "stocksy.com", "pond5.com", "twenty20.com",
}
STOCK_PATH = re.compile(r"(shutterstock|istock|gettyimages|depositphotos|dreamstime|freepik|unsplash|pexels|pixabay|adobestock|stock-photo)", re.I)


def stock_reason(*urls: str) -> str | None:
    for url in urls:
        if not url:
            continue
        host = urlsplit(url).netloc.lower().removeprefix("www.")
        for d in STOCK_DOMAINS:
            if host == d or host.endswith("." + d):
                return f"изображение с фотобанка {d}"
        if STOCK_PATH.search(url):
            return "в адресе файла есть признаки фотобанка"
    return None
