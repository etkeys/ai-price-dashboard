"""Flask extension instances.

Extensions are created here without an app and bound later inside
`create_app()` via `init_app()`.
"""

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
migrate = Migrate()
