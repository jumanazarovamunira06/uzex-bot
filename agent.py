import sqlite3


def search_uzex_data(query_text):
  conn = sqlite3.connect("uzex.db")
  cursor = conn.cursor()

  # Misol uchun: shartnomalar yoki bitimlar jadvalidan qidirish logikasi
  # Bu yerda oddiy qidiruv yoki maxsus SQL so'rovlar yozish mumkin
  results = []
  try:
    # Contracts jadvalidan qidirib ko'ramiz
    cursor.execute(
        "SELECT * FROM contracts WHERE "
        '"Наименование продукта" LIKE ? OR "Марка товара" LIKE ? LIMIT 5',
        (f"%{query_text}%", f"%{query_text}%"),
    )
    results = cursor.fetchall()
  except Exception as e:
    print(f"Xatolik: {e}")

  conn.close()
  return results


# Test qilib ko'rish uchun
if __name__ == "__main__":
  user_query = input("Qaysi tovarni yoki ma'lumotni qidirmoqchisiz?: ")
  data = search_uzex_data(user_query)

  if data:
    print(f"Topilgan ma'lumotlar ({len(data)} ta):")
    for row in data:
      print(row)
  else:
    print("Kechirasiz, bu ma'lumot bazada mavjud emas.")