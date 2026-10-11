"""Competitor product assignments (one product per competitor).

Status meanings:
  candidate  - ASIN found in web-search results that point to an amazon.com /dp/ URL,
               but the live listing could not be opened from this environment.
  verified   - ASIN confirmed by a successful review retrieval whose records match the
               product (set automatically in the collection log, not here).

Every entry records where the ASIN came from. Nothing here is a review observation.
"""

PRODUCTS = [
    {
        "competitor": "Maldon Salt",
        "asin": "B00017028M",
        "product_name": "Maldon Salt, Sea Salt Flakes, 8.5 oz (240 g)",
        "package_size": "8.5 oz box",
        "product_type": "Plain flake finishing salt",
        "listing_url": "https://www.amazon.com/dp/B00017028M",
        "asin_evidence": [
            "Web search (2026-10-11) returned amazon.com/dp/B00017028M titled 'Maldon Salt, Sea Salt Flakes, 8.5 oz (240 g)'",
            "Same ASIN on amazon.de / amazon.in / amazon.fr listings for Maldon 250 g",
        ],
    },
    {
        "competitor": "Jacobsen Salt Co.",
        "asin": "B01M32JS5F",
        "product_name": "Jacobsen Salt Co. Pure Flake Sea Salt, 4 oz",
        "package_size": "4 oz",
        "product_type": "Plain flake finishing salt",
        "listing_url": "https://www.amazon.com/dp/B01M32JS5F",
        "asin_evidence": [
            "Web search (2026-10-11) returned amazon.com/.../dp/B01M32JS5F 'Jacobsen Salt Co. Pure Flake Sea Salt ... 4 Oz'",
            "wholefoodsmarket.com product URL '4-ounce-pack-of-1-b01m32js5f'",
        ],
    },
    {
        "competitor": "SaltWorks",
        "asin": "B077NRHK1F",
        "product_name": "SaltWorks Pacific Blue Sea Salt, Kosher Flake, 8 oz pour-spout pouch",
        "package_size": "8 oz pouch",
        "product_type": "Plain flake finishing salt",
        "listing_url": "https://www.amazon.com/dp/B077NRHK1F",
        "asin_evidence": [
            "Web search (2026-10-11) returned amazon.com/.../dp/B077NRHK1F 'SaltWorks Pacific Blue Sea Salt, Artisan Pour Spout Pouch, Kosher Flake, 8 Ounce'",
        ],
    },
    {
        "competitor": "The Spice Lab",
        "asin": "B0030MZMIK",
        "product_name": "The Spice Lab Cyprus White Flake Kosher Salt, 8 oz bag",
        "package_size": "8 oz bag",
        "product_type": "Plain flake finishing salt",
        "listing_url": "https://www.amazon.com/dp/B0030MZMIK",
        "asin_evidence": [
            "Web search (2026-10-11) returned amazon.com/.../dp/B0030MZMIK 'The Spice Lab Cyprus White Flake Kosher Salt - 8 Oz. Bag'",
        ],
    },
    {
        "competitor": "Redmond Real Salt",
        "asin": "B071FNYFWW",
        "product_name": "Redmond Real Salt - Ancient Fine Sea Salt, Unrefined, 16 oz pouch",
        "package_size": "16 oz pouch",
        "product_type": "Fine-grain everyday mineral salt (NOT a flake finishing salt)",
        "listing_url": "https://www.amazon.com/dp/B071FNYFWW",
        "asin_evidence": [
            "Web search (2026-10-11) returned amazon.com/.../dp/B071FNYFWW 'Redmond Real Salt - Ancient Fine Sea Salt, Unrefined, 16 Oz Pouch (1 Pack)'",
        ],
    },
]

COMPARABILITY_NOTE = (
    "Four products are plain flake finishing salts; Redmond Real Salt sells no flake salt, "
    "so its fine-grain everyday salt is used. Its loyalty reflects a different use case "
    "(daily cooking salt) and package size, which limits direct comparison."
)
