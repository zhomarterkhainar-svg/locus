import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Тесты должны идти в пустом кэше: иначе настоящие карты, собранные ml/seed_osm_cache.py
# или прошлым запуском сервиса, подменяют ответы подставных API и результаты «плавают».
_TMP = tempfile.mkdtemp(prefix="candid-tests-")
os.environ["CACHE_DIR"] = str(Path(_TMP) / "cache")
os.environ["SEED_CACHE_DIR"] = str(Path(_TMP) / "seed")
os.environ["PREWARM"] = "false"
# Офлайн-тесты проверяют логику сборки, а не скорость: внешние API подменены и отвечают мгновенно,
# зато машина CI бывает занята. С боевым бюджетом в 10 секунд результат начинает зависеть от нагрузки,
# поэтому в тестах бюджет щедрый - проверяется состав профиля и фактов, а не время.
os.environ["TOTAL_BUDGET"] = "25"
os.environ["FACTS_BUDGET"] = "8"
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")
