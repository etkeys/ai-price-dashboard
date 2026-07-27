"""Example Price data model."""

from app.extensions import db


class Price(db.Model):
    """Represents a price observation."""

    __tablename__ = "prices"

    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(32), nullable=False, index=True)
    price = db.Column(db.Numeric(18, 8), nullable=False)
    currency = db.Column(db.String(8), nullable=False, default="USD")
    source = db.Column(db.String(128), nullable=True)
    recorded_at = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Price {self.symbol}={self.price} {self.currency}>"
