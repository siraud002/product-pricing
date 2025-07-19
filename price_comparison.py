import csv
import re
import time
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from urllib.parse import urlparse, parse_qs, quote_plus

try:
    import pdfplumber
    import pandas as pd
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    raise SystemExit(f"Missing dependency: {e.name}. Please install required packages.")


@dataclass
class ProductItem:
    name: str
    vendor: str
    quantity: int
    unit_price: float
    freight: float = 0.0
    notes: str = ""


@dataclass
class VendorOption:
    vendor: str
    price: Optional[float]
    freight: Optional[float]
    url: str


class PriceComparator:
    def __init__(self, search_delay: float = 2.0):
        self.search_delay = search_delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/114.0 Safari/537.36"
            )
        })

    def parse_input(self, path: str) -> List[ProductItem]:
        if path.lower().endswith(".pdf"):
            return self._parse_pdf(path)
        else:
            return self._parse_excel(path)

    def _parse_pdf(self, path: str) -> List[ProductItem]:
        items: List[ProductItem] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    for row in table[1:]:
                        try:
                            name, vendor, qty, price, freight, *rest = row + ["", ""]
                            item = ProductItem(
                                name=name.strip(),
                                vendor=vendor.strip(),
                                quantity=int(qty),
                                unit_price=float(str(price).replace("$", "")),
                                freight=float(str(freight).replace("$", "") or 0),
                                notes=" ".join(rest).strip(),
                            )
                            items.append(item)
                        except Exception:
                            continue
        return items

    def _parse_excel(self, path: str) -> List[ProductItem]:
        df = pd.read_excel(path)
        items: List[ProductItem] = []
        for _, row in df.iterrows():
            try:
                item = ProductItem(
                    name=str(row.get("Item Name")),
                    vendor=str(row.get("Vendor")),
                    quantity=int(row.get("Quantity", 1)),
                    unit_price=float(row.get("Unit Price", 0)),
                    freight=float(row.get("Freight", 0)),
                    notes=str(row.get("Notes", "")),
                )
                items.append(item)
            except Exception:
                continue
        return items

    def google_search(self, query: str, num_results: int = 3) -> List[Dict[str, str]]:
        url = f"https://www.google.com/search?q={quote_plus(query)}&num={num_results}"
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results: List[Dict[str, str]] = []
        for g in soup.select("div.g"):
            a = g.find("a", href=True)
            if not a:
                continue
            link = self._clean_google_link(a["href"])
            title = a.get_text(strip=True)
            if link:
                results.append({"title": title, "link": link})
            if len(results) >= num_results:
                break
        time.sleep(self.search_delay)
        return results

    @staticmethod
    def _clean_google_link(href: str) -> Optional[str]:
        parsed = urlparse(href)
        if parsed.path == "/url":
            q = parse_qs(parsed.query).get("q")
            if q:
                return q[0]
        return href

    def fetch_product_info(self, url: str) -> VendorOption:
        try:
            r = self.session.get(url, timeout=10)
            r.raise_for_status()
        except Exception:
            return VendorOption(vendor="", price=None, freight=None, url=url)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        price_match = re.search(r"\$(\d+[\d,.]*)", text)
        price = float(price_match.group(1).replace(",", "")) if price_match else None
        freight_match = re.search(r"shipping[^\$]*\$(\d+[\d,.]*)", text, re.I)
        freight = float(freight_match.group(1).replace(",", "")) if freight_match else None
        vendor = urlparse(url).netloc
        return VendorOption(vendor=vendor, price=price, freight=freight, url=url)

    def compare_prices(self, items: List[ProductItem]) -> List[Dict[str, str]]:
        results = []
        for item in items:
            query = f"{item.name} buy online"
            search_results = self.google_search(query, num_results=3)
            options = []
            for r in search_results:
                info = self.fetch_product_info(r["link"])
                options.append(info)
            best_total = None
            for opt in options:
                if opt.price is None:
                    continue
                total = opt.price + (opt.freight or 0)
                if best_total is None or total < best_total:
                    best_total = total
            result = {
                "Item Name": item.name,
                "Original Vendor": item.vendor,
                "Quantity": item.quantity,
                "Original Unit Price": item.unit_price,
                "Original Freight": item.freight,
                "Best Total Price": best_total,
            }
            for i, opt in enumerate(options, 1):
                result[f"Alt Vendor {i}"] = f"{opt.vendor}, {opt.price}, {opt.freight}, {opt.url}"
            results.append(result)
        return sorted(results, key=lambda r: r.get("Best Total Price") or float("inf"))

    def to_csv(self, data: List[Dict[str, str]], path: str):
        if not data:
            return
        keys = list(data[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for row in data:
                writer.writerow(row)


def main(infile: str, outfile: str):
    comp = PriceComparator()
    items = comp.parse_input(infile)
    results = comp.compare_prices(items)
    comp.to_csv(results, outfile)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Product price comparison tool")
    parser.add_argument("infile", help="Path to input PDF or Excel file")
    parser.add_argument("outfile", help="Path to output CSV file")
    args = parser.parse_args()
    main(args.infile, args.outfile)
