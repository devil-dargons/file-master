# 清理验证脚本误入真实数据库的假记录（只删 files/file_meta/file_tags，不动 tags 表）
import sys
sys.path.insert(0, 'd:/code/python/file-master')
from src.db.database import DatabaseManager

db = DatabaseManager()
conn = db.get_connection()

# 1. 定位假记录：
#    a) verify_lan.py: name in p0/p1/p2.jpg, added_time=1700000000+i, 路径在临时目录
#    b) verify_chips.py: path LIKE '/t/%', added_time=1
fake_ids = [r[0] for r in conn.execute(
    "SELECT id FROM files WHERE path LIKE '/t/%'").fetchall()]
fake_ids += [r[0] for r in conn.execute(
    "SELECT id FROM files WHERE name IN ('p0.jpg','p1.jpg','p2.jpg')"
    " AND added_time BETWEEN 1700000000 AND 1700000002").fetchall()]
fake_ids = sorted(set(fake_ids))
print('fake file ids:', fake_ids)

if not fake_ids:
    print('nothing to clean')
    sys.exit(0)

ph = ','.join('?' * len(fake_ids))
# 2. 删关联
n1 = conn.execute(f"DELETE FROM file_tags WHERE file_id IN ({ph})", fake_ids).rowcount
n2 = conn.execute(f"DELETE FROM file_meta WHERE file_id IN ({ph})", fake_ids).rowcount
n3 = conn.execute(f"DELETE FROM files WHERE id IN ({ph})", fake_ids).rowcount
conn.commit()
print(f'deleted: file_tags={n1}, file_meta={n2}, files={n3}')

# 3. 复核：确认无残留
left = conn.execute(
    "SELECT COUNT(*) FROM files WHERE path LIKE '/t/%' OR (name IN ('p0.jpg','p1.jpg','p2.jpg') AND added_time BETWEEN 1700000000 AND 1700000002)"
).fetchone()[0]
print('remaining fake rows:', left)
print('total files now:', conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
