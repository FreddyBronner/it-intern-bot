import aiosqlite
import os

DB_PATH = os.getenv("DB_PATH", "internships.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                name TEXT,
                stack TEXT,          
                city TEXT,           
                course INTEGER,      
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS internships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                title TEXT NOT NULL,
                stack TEXT,           
                city TEXT,
                remote INTEGER DEFAULT 0,
                salary TEXT,         
                description TEXT,
                url TEXT,            
                deadline TEXT,       
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                stack_filter TEXT,    -- на какой стек подписан
                city_filter TEXT,     -- на какой город
                active INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                internship_id INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (internship_id) REFERENCES internships(id),
                UNIQUE(user_id, internship_id)
            );
        """)
        await db.commit()


# Пользователи

async def get_or_create_user(telegram_id: int, name: str | None = None) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        user = await cursor.fetchone()
        if user:
            return dict(user)

        await db.execute(
            "INSERT INTO users (telegram_id, name) VALUES (?, ?)",
            (telegram_id, name),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        return dict(await cursor.fetchone())


async def update_user_profile(telegram_id: int, stack: str = None, city: str = None, course: int = None):
    """Обновляет профиль пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        fields = []
        values = []
        if stack is not None:
            fields.append("stack = ?")
            values.append(stack)
        if city is not None:
            fields.append("city = ?")
            values.append(city)
        if course is not None:
            fields.append("course = ?")
            values.append(course)
        if not fields:
            return
        values.append(telegram_id)
        await db.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE telegram_id = ?",
            values,
        )
        await db.commit()


async def get_user(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


# Стажировки

async def search_internships(
    stack: str = None,
    city: str = None,
    remote: bool = None,
    limit: int = 10,
) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM internships WHERE 1=1"
        params = []

        if stack:
            tags = [t.strip() for t in stack.split(",")]
            tag_conditions = " OR ".join(["stack LIKE ?" for _ in tags])
            query += f" AND ({tag_conditions})"
            params.extend([f"%{tag}%" for tag in tags])

        if city:
            query += " AND (city LIKE ? OR remote = 1)"
            params.append(f"%{city}%")

        if remote is True:
            query += " AND remote = 1"

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_internship(internship_id: int) -> dict | None:
    """Получает стажировку по ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM internships WHERE id = ?", (internship_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_internships(limit: int = 50) -> list[dict]:
    """Все стажировки (для просмотра)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM internships ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in await cursor.fetchall()]


async def get_companies() -> list[str]:
    """Список уникальных компаний."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT company FROM internships ORDER BY company"
        )
        return [row[0] for row in await cursor.fetchall()]


#Избранное

async def add_favorite(telegram_id: int, internship_id: int) -> bool:
    """Добавляет стажировку в избранное. Возвращает True если добавлено."""
    user = await get_user(telegram_id)
    if not user:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO favorites (user_id, internship_id) VALUES (?, ?)",
                (user["id"], internship_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False  # уже в избранном


async def remove_favorite(telegram_id: int, internship_id: int):
    """Удаляет из избранного."""
    user = await get_user(telegram_id)
    if not user:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM favorites WHERE user_id = ? AND internship_id = ?",
            (user["id"], internship_id),
        )
        await db.commit()


async def get_favorites(telegram_id: int) -> list[dict]:
    """Список избранных стажировок."""
    user = await get_user(telegram_id)
    if not user:
        return []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT i.* FROM internships i
               JOIN favorites f ON f.internship_id = i.id
               WHERE f.user_id = ?
               ORDER BY i.company""",
            (user["id"],),
        )
        return [dict(r) for r in await cursor.fetchall()]


#Подписки

async def add_subscription(telegram_id: int, stack_filter: str = None, city_filter: str = None):
    user = await get_user(telegram_id)
    if not user:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO subscriptions (user_id, stack_filter, city_filter) VALUES (?, ?, ?)",
            (user["id"], stack_filter, city_filter),
        )
        await db.commit()


async def get_active_subscriptions() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT s.*, u.telegram_id
               FROM subscriptions s
               JOIN users u ON u.id = s.user_id
               WHERE s.active = 1"""
        )
        return [dict(r) for r in await cursor.fetchall()]


async def remove_subscription(telegram_id: int):
    user = await get_user(telegram_id)
    if not user:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM subscriptions WHERE user_id = ?", (user["id"],)
        )
        await db.commit()


#Добавление стажировок (для seed и админки)

async def add_internship(
    company: str,
    title: str,
    stack: str = None,
    city: str = None,
    remote: int = 0,
    salary: str = None,
    description: str = None,
    url: str = None,
    deadline: str = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO internships
               (company, title, stack, city, remote, salary, description, url, deadline)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company, title, stack, city, remote, salary, description, url, deadline),
        )
        await db.commit()
        return cursor.lastrowid
