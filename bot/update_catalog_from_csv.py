"""Build the Mini App catalog and equipment JSON from the published CSV sheet."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "catalog.csv"

LEVELS = {
    "Стажер Media BMSTU + СО/ССФ": None,
    "Активист Media BMSTU": "акт",
    "Глава отдела Media BMSTU": "глава",
    "НЕ ВЫДАЕТСЯ": "none",
}

SHORT_OVERRIDES = {
    ("C-Stand", "GreenBean"): "C-Stand GreenBean",
    ("C-Stand", "Avenger"): "C-Stand Avenger",
    ("Зарядка NP-FW970", "Набор 2 аккумуляторов"): "Набор NP-FW970",
}


def unique_short(short: str, full: str) -> str:
    for (source, marker), replacement in SHORT_OVERRIDES.items():
        if short == source and marker.casefold() in full.casefold():
            return replacement
    return short


def parse_catalog(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    categories: list[dict] = []
    category_by_name: dict[str, dict] = {}
    category = ""
    subcategory = ""
    current: dict | None = None

    for row_number, row in enumerate(rows, start=2):
        next_category = row["Категория"].strip()
        if next_category:
            category = next_category
            subcategory = ""
        next_subcategory = row["Подкатегория "].strip()
        if next_subcategory:
            subcategory = next_subcategory

        short = row["Короткое имя"].strip()
        number = row["Номера"].strip()
        if short:
            if not category:
                raise ValueError(f"Строка {row_number}: позиция без категории")
            full = row["Полное наименование"].strip() or short
            total_text = row["Общее кол-во"].strip()
            if not total_text.isdigit() or int(total_text) < 1:
                raise ValueError(f"Строка {row_number}: неверное общее количество")
            access = row["Допуск"].strip()
            if access not in LEVELS:
                raise ValueError(f"Строка {row_number}: неизвестный допуск {access!r}")
            current = {
                "short": unique_short(short, full),
                "full": full,
                "total": int(total_text),
                "level": LEVELS[access],
                "numbers": [],
                "_subcategory": subcategory,
                "_row": row_number,
            }
            cat = category_by_name.get(category)
            if cat is None:
                cat = {"cat": category, "items": []}
                category_by_name[category] = cat
                categories.append(cat)
            cat["items"].append(current)
        if current is not None and number:
            if not number.isdigit() or int(number) < 1:
                raise ValueError(f"Строка {row_number}: неверный номер экземпляра")
            value = int(number)
            if value not in current["numbers"]:
                current["numbers"].append(value)

    seen: dict[str, int] = {}
    for cat in categories:
        for item in cat["items"]:
            if not item["numbers"]:
                item["numbers"] = list(range(1, item["total"] + 1))
            previous = seen.get(item["short"])
            if previous:
                raise ValueError(
                    f"Неуникальное короткое имя {item['short']!r}: "
                    f"строки {previous} и {item['_row']}"
                )
            seen[item["short"]] = item["_row"]
    return categories


def public_catalog(categories: list[dict]) -> list[dict]:
    return [
        {
            "cat": cat["cat"],
            "items": [
                {key: value for key, value in item.items() if not key.startswith("_")}
                for item in cat["items"]
            ],
        }
        for cat in categories
    ]


def equipment_catalog(categories: list[dict]) -> list[dict]:
    output = []
    for cat in categories:
        subcat_of = {
            item["short"]: item["_subcategory"]
            for item in cat["items"]
            if item["_subcategory"]
        }
        items = []
        for source in cat["items"]:
            item = {
                key: value for key, value in source.items() if not key.startswith("_")
            }
            item["units"] = [
                {"n": number, "level": item["level"]} for number in item["numbers"]
            ]
            items.append(item)
        output.append({"cat": cat["cat"], "subcat_of": subcat_of, "items": items})
    return output


def write_outputs(categories: list[dict]) -> None:
    public = public_catalog(categories)
    js = "window.OBORUDKA_CATALOG = " + json.dumps(
        public, ensure_ascii=False, indent=2
    ) + ";\n"
    (ROOT / "prototype" / "catalog.js").write_text(js, encoding="utf-8")
    (ROOT / "bot" / "catalog.js").write_text(js, encoding="utf-8")
    (ROOT / "bot" / "equipment.json").write_text(
        json.dumps(equipment_catalog(categories), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", nargs="?", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()
    categories = parse_catalog(args.csv)
    write_outputs(categories)
    item_count = sum(len(cat["items"]) for cat in categories)
    unit_count = sum(
        len(item["numbers"]) for cat in categories for item in cat["items"]
    )
    print(
        f"Готово: {len(categories)} категорий, "
        f"{item_count} позиций, {unit_count} допустимых номеров"
    )


if __name__ == "__main__":
    main()
