import sqlite3

conn = sqlite3.connect("uzex.db")
cursor = conn.cursor()

# Jadvaldagi ustun nomlarini ko'ramiz
cursor.execute("PRAGMA table_info(contracts);")
print("Ustunlar:", [col[1] for col in cursor.fetchall()])

# Ba'zi mahsulot nomlarini chiqaramiz
cursor.execute('SELECT "Наименование продукта" FROM contracts LIMIT 5')
print("\nMahsulotlar namunasi:")
for row in cursor.fetchall():
  print(row[0])

conn.close()