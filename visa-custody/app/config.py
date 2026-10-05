"""全局配置：路径、密钥与岗位常量。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VCD_DATA_DIR", BASE_DIR / "data"))
PHOTOS_DIR = DATA_DIR / "photos"
DB_PATH = DATA_DIR / "custody.db"
DATABASE_URL = os.environ.get(
    "VCD_DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}"
)

# 演示用途的默认密钥；生产环境通过环境变量覆盖
SECRET_KEY = os.environ.get("VCD_SECRET", "dev-secret-visa-custody-2026")
TOKEN_TTL_SECONDS = 60 * 60 * 12

DATA_DIR.mkdir(parents=True, exist_ok=True)
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

# 岗位角色
ROLE_ADMIN = "admin"      # 管理员：全量数据
ROLE_STAFF = "staff"      # 经手岗位（前台/收件员）：仅本人名下客户材料含照片
ROLE_COURIER = "courier"  # 配送员：只负责配送交接，不可查看证件照片

# 可以接触、查看证件原件照片的岗位
PHOTO_ALLOWED_ROLES = {ROLE_ADMIN, ROLE_STAFF}
