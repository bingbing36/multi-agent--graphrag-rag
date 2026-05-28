from __future__ import annotations

import os
import random


Base = declarative_base()


class SalesData(Base):
    __tablename__ = "sales_data"

    sales_id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("product_information.product_id"))
    employee_id = Column(Integer)
    customer_id = Column(Integer, ForeignKey("customer_information.customer_id"))
    sale_date = Column(String(50))
    quantity = Column(Integer)
    amount = Column(Float)
    discount = Column(Float)


class CustomerInformation(Base):
    __tablename__ = "customer_information"

    customer_id = Column(Integer, primary_key=True)
    customer_name = Column(String(50))
    contact_info = Column(String(100))
    region = Column(String(50))
    customer_type = Column(String(50))


class ProductInformation(Base):
    __tablename__ = "product_information"

    product_id = Column(Integer, primary_key=True)
    product_name = Column(String(50))
    category = Column(String(50))
    unit_price = Column(Float)
    stock_level = Column(Integer)


class CompetitorAnalysis(Base):
    __tablename__ = "competitor_analysis"

    competitor_id = Column(Integer, primary_key=True)
    competitor_name = Column(String(50))
    region = Column(String(50))
    market_share = Column(Float)

def seed_demo_data() -> None:
    """写入 Faker 模拟数据"""
    session = SessionLocal()
    try:
        if session.query(SalesData).first():
            return

        try:
            from faker import Faker
        except ImportError as exc:
            raise ImportError(
                "faker is required for demo data. Install via: pip install faker"
            ) from exc

        fake = Faker("zh_CN")
        customer_count = int(os.getenv("FAKE_CUSTOMER_COUNT", "50"))
        product_count = int(os.getenv("FAKE_PRODUCT_COUNT", "20"))
        competitor_count = int(os.getenv("FAKE_COMPETITOR_COUNT", "10"))
        sales_count = int(os.getenv("FAKE_SALES_COUNT", "100"))

        customers: list[CustomerInformation] = []
        for _ in range(customer_count):
            customers.append(
                CustomerInformation(
                    customer_name=fake.name(),
                    contact_info=fake.phone_number(),
                    region=fake.province(),
                    customer_type=random.choice(["Retail", "Wholesale"]),
                )
            )
        session.add_all(customers)
        session.flush()

        products: list[ProductInformation] = []
        for _ in range(product_count):
            products.append(
                ProductInformation(
                    product_name=fake.word(),
                    category=random.choice(
                        ["Electronics", "Clothing", "Furniture", "Food", "Toys"]
                    ),
                    unit_price=round(random.uniform(10.0, 1000.0), 2),
                    stock_level=random.randint(10, 100),
                )
            )
        session.add_all(products)
        session.flush()

        competitors: list[CompetitorAnalysis] = []
        for _ in range(competitor_count):
            competitors.append(
                CompetitorAnalysis(
                    competitor_name=fake.company(),
                    region=fake.province(),
                    market_share=round(random.uniform(0.01, 0.2), 4),
                )
            )
        session.add_all(competitors)
        session.flush()

        customer_ids = [item.customer_id for item in customers]
        product_ids = [item.product_id for item in products]

        sales: list[SalesData] = []
        for _ in range(sales_count):
            sales.append(
                SalesData(
                    product_id=random.choice(product_ids),
                    employee_id=random.randint(1, 10),
                    customer_id=random.choice(customer_ids),
                    sale_date=fake.date_between(start_date="-1y", end_date="today").strftime(
                        "%Y-%m-%d"
                    ),
                    quantity=random.randint(1, 10),
                    amount=round(random.uniform(50.0, 5000.0), 2),
                    discount=round(random.uniform(0.0, 0.15), 6),
                )
            )
        session.add_all(sales)
        session.commit()
    finally:
        session.close()
