# services/ — Business logic layer for webmarket.
#
# Each module exports async functions that receive db: AsyncIOMotorDatabase
# and raise domain exceptions from services.exceptions.
# Routers consume these services, translating domain exceptions to HTTPException.
