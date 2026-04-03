"""
Модели данных Ozon Parser v2
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ProductCard:
    """Карточка товара Ozon."""

    url: str
    product_id: Optional[str] = None
    sku_id: Optional[str] = None
    title: Optional[str] = None
    brand: Optional[str] = None
    price: Optional[float] = None
    price_original: Optional[float] = None
    discount_percent: Optional[int] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    seller_name: Optional[str] = None
    seller_id: Optional[str] = None
    category: Optional[str] = None
    category_path: list = field(default_factory=list)
    images: list = field(default_factory=list)
    in_stock: bool = True
    stock_quantity: Optional[int] = None
    attributes: dict = field(default_factory=dict)
    description: Optional[str] = None
    short_description: Optional[str] = None
    variants: list = field(default_factory=list)
    delivery_info: Optional[str] = None
    parse_status: str = "pending"
    error_message: Optional[str] = None
    parse_time: Optional[float] = None
    parse_method: str = "unknown"
    raw_json: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "product_id": self.product_id,
            "sku_id": self.sku_id,
            "title": self.title,
            "brand": self.brand,
            "price": self.price,
            "price_original": self.price_original,
            "discount_percent": self.discount_percent,
            "rating": self.rating,
            "reviews_count": self.reviews_count,
            "seller_name": self.seller_name,
            "seller_id": self.seller_id,
            "category": self.category,
            "category_path": str(self.category_path),
            "images": str(self.images),
            "in_stock": self.in_stock,
            "stock_quantity": self.stock_quantity,
            "attributes": str(self.attributes),
            "description": self.description,
            "short_description": self.short_description,
            "variants": str(self.variants),
            "delivery_info": self.delivery_info,
            "parse_status": self.parse_status,
            "error_message": self.error_message,
            "parse_time": self.parse_time,
            "parse_method": self.parse_method,
        }


@dataclass
class ParseStats:
    """Статистика парсинга."""

    total_urls: int = 0
    success: int = 0
    errors: int = 0
    blocked: int = 0
    not_found: int = 0
    retried: int = 0
    avg_parse_time: float = 0.0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
