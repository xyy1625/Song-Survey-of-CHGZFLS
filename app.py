# -*- coding: utf-8 -*-
"""
FM 点歌台应用 - Flask 后端服务
用于管理歌曲点播、审核、配额和用户权限的 Web 应用。
"""

from flask import Flask, render_template, request, redirect, session, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import pandas as pd
import io
from functools import wraps

# Flask 应用初始化
app = Flask(__name__)
app.secret_key = "secret-key"

# 数据库配置
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# SQLAlchemy 数据库实例
db = SQLAlchemy(app)

# ======================
# 权限装饰器
# ======================
def role_required(*roles):
    """
    角色权限装饰器
    检查用户角色是否在允许的角色列表中。
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if session.get("role") not in roles:
                return "Unauthorized"
            return f(*args, **kwargs)
        return wrapper
    return decorator

# ======================
# 数据模型定义
# ======================
class Response(db.Model):
    """
    歌曲响应模型 - 存储用户提交的歌曲信息和审核状态
    """
    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(50))  # 班级名称
    name = db.Column(db.String(50))        # 学生姓名
    song = db.Column(db.String(100))       # 歌曲名称
    author = db.Column(db.String(100))     # 歌曲作者
    timeslot = db.Column(db.String(50))    # 播放时段
    created_at = db.Column(db.DateTime, default=datetime.now)  # 提交时间
    status = db.Column(db.String(20), default="未审核")        # 审核状态

class Quota(db.Model):
    """
    配额模型 - 管理每个时段的歌曲数量限制
    """
    id = db.Column(db.Integer, primary_key=True)
    timeslot = db.Column(db.String(50), unique=True)  # 时段名称
    count = db.Column(db.Integer, default=0)          # 当前已用数量
    limit = db.Column(db.Integer, default=5)          # 限制数量

class User(db.Model):
    """
    用户模型 - 管理系统用户和权限
    """
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)  # 用户名
    password = db.Column(db.String(100))              # 密码
    role = db.Column(db.String(20), default="operator")  # 角色: admin/operator/reviewer

class ResponseHistory(db.Model):
    """
    历史响应模型 - 备份已清空的歌曲数据
    """
    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(50))
    name = db.Column(db.String(50))
    song = db.Column(db.String(100))
    author = db.Column(db.String(100))
    timeslot = db.Column(db.String(50))
    created_at = db.Column(db.DateTime)      # 原始提交时间
    status = db.Column(db.String(20))        # 审核状态

# ======================
# 常量定义
# ======================
# 定义可用的播放时段
TIMESLOTS = [
    "周一午间", "周一晚间", "周二午间",
    "周二晚间", "周三午间", "周三晚间",
    "周四午间", "周四晚间", "周五午间"
]

# ======================
# 数据库初始化函数
# ======================
def init_db():
    """
    初始化数据库
    创建所有表，初始化默认配额和管理员用户。
    """
    with app.app_context():
        # 创建所有表
        db.create_all()

        # 初始化配额数据
        for t in TIMESLOTS:
            if not Quota.query.filter_by(timeslot=t).first():
                db.session.add(Quota(timeslot=t, count=0, limit=5))

        # 初始化管理员用户
        user = User.query.filter_by(username="admin").first()
        if not user:
            db.session.add(User(username="admin", password="Chgzfls_2026", role="admin"))
        else:
            user.role = "admin"

        # 提交更改
        db.session.commit()

# ======================
# 前端展示路由
# ======================
@app.route("/")
def list_page():
    """
    首页路由 - 显示已审核通过的歌曲列表
    """
    responses = Response.query.filter_by(status="审核通过") \
        .order_by(Response.created_at.desc()).all()

    return render_template("index.html", responses=responses)

@app.route("/song")
def index():
    """
    歌曲提交页面 - 显示配额信息供用户选择时段
    """
    quotas = Quota.query.all()
    return render_template("song.html", quotas=quotas)

# ======================
# 表单提交路由
# ======================
@app.route("/submit", methods=["POST"])
def submit():
    """
    歌曲提交处理 - 验证配额并保存数据
    """
    timeslot = request.form["timeslot"]

    # 检查配额是否已满
    quota = Quota.query.filter_by(timeslot=timeslot).first()
    if quota.count >= quota.limit:
        return "该时间段已满"

    # 创建新的响应记录
    data = Response(
        class_name=request.form["class"],
        name=request.form["name"],
        song=request.form["song"],
        author=request.form["author"],
        timeslot=timeslot
    )

    # 更新配额计数
    quota.count += 1
    db.session.add(data)
    db.session.commit()

    return "提交成功"

# ======================
# 认证路由
# ======================
@app.route("/admin", methods=["GET", "POST"])
def admin():
    """
    管理员登录页面 - 处理登录逻辑并重定向到相应页面
    """
    if request.method == "POST":
        session.clear()
        username = request.form.get("username")
        password = request.form.get("password")

        # 验证用户凭据
        user = User.query.filter_by(username=username).first()
        if user and user.password == password:
            session["username"] = user.username
            session["role"] = user.role

            # 根据角色重定向
            if user.role == "admin":
                return redirect("/admin_home")
            elif user.role == "reviewer":
                return redirect("/control")
            elif user.role == "operator":
                return redirect("/view")

        return render_template("login.html", error="用户名或密码错误")

    return render_template("login.html")

@app.route("/logout")
def logout():
    """
    登出路由 - 清除会话并重定向到登录页
    """
    session.clear()
    return redirect("/admin")

# ======================
# 后台管理路由
# ======================
@app.route("/admin_home")
@role_required("admin")
def admin_home():
    """
    管理员后台首页 - 显示所有数据供管理
    """
    quotas = Quota.query.all()
    responses = Response.query.order_by(Response.created_at.desc()).all()
    users = User.query.all()

    return render_template(
        "admin.html",
        quotas=quotas,
        responses=responses,
        users=users
    )

@app.route("/control")
@role_required("reviewer")
def control():
    """
    审核员控制台 - 显示所有响应供审核
    """
    quotas = Quota.query.all()
    responses = Response.query.order_by(Response.created_at.desc()).all()  # 不筛选状态
    return render_template("control.html", quotas=quotas, responses=responses)

@app.route("/view")
@role_required("operator")
def view():
    """
    操作员查看页面 - 显示所有数据供查看
    """
    quotas = Quota.query.all()
    responses = Response.query.order_by(Response.created_at.desc()).all()
    return render_template("view.html", quotas=quotas, responses=responses)

# ======================
# 数据更新路由
# ======================
@app.route("/update_quota", methods=["POST"])
@role_required("admin")
def update_quota():
    """
    更新配额限制 - 批量更新所有时段的限制数量
    """
    for q in Quota.query.all():
        new_limit = request.form.get(q.timeslot)
        if new_limit:
            q.limit = int(new_limit)
    db.session.commit()
    return redirect("/admin_home")

@app.route("/update_status/<int:response_id>", methods=["POST"])
@role_required("reviewer", "admin")
def update_status(response_id):
    """
    更新审核状态 - 修改指定响应的审核状态
    """
    r = Response.query.get(response_id)
    if not r:
        return "未找到数据"

    new_status = request.form.get("status")
    if new_status in ["未审核", "审核通过", "审核驳回"]:
        r.status = new_status
        db.session.commit()

    # 根据角色重定向
    if session["role"] == "admin":
        return redirect("/admin_home")
    return redirect("/control")

# ======================
# 数据导出路由
# ======================
@app.route("/export")
@role_required("admin")
def export():
    """
    导出 Excel 文件 - 生成包含本周和历史歌单的 Excel 文件
    """
    now = datetime.now()
    start_of_week = now - timedelta(days=now.weekday())

    # 获取本周歌单数据
    week_data = Response.query.order_by(Response.created_at.desc()).all()

    # 获取历史歌单数据
    all_data = ResponseHistory.query.order_by(ResponseHistory.created_at.desc()).all()

    # 转换为 DataFrame
    df_week = pd.DataFrame([{
        "班级": d.class_name,
        "姓名": d.name,
        "歌曲": d.song,
        "作者": d.author,
        "播放时段": d.timeslot,
        "状态": d.status,
        "提交时间": d.created_at.strftime("%Y-%m-%d %H:%M:%S")
    } for d in week_data])

    df_all = pd.DataFrame([{
        "班级": d.class_name,
        "姓名": d.name,
        "歌曲": d.song,
        "作者": d.author,
        "播放时段": d.timeslot,
        "状态": d.status,
        "提交时间": d.created_at.strftime("%Y-%m-%d %H:%M:%S")
    } for d in all_data])

    # 生成 Excel 文件
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_week.to_excel(writer, index=False, sheet_name="本周歌单")
        df_all.to_excel(writer, index=False, sheet_name="历史歌单")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="歌单数据.xlsx"
    )

# ======================
# 数据重置路由
# ======================
@app.route("/reset")
@role_required("admin")
def reset():
    """
    清空本周数据 - 将当前数据备份到历史表并重置配额计数
    """
    responses = Response.query.all()

    # 备份到历史表
    for r in responses:
        history = ResponseHistory(
            class_name=r.class_name,
            name=r.name,
            song=r.song,
            author=r.author,
            timeslot=r.timeslot,
            created_at=r.created_at,
            status=r.status
        )
        db.session.add(history)

    # 删除当前数据
    Response.query.delete()

    # 重置配额计数
    for q in Quota.query.all():
        q.count = 0

    db.session.commit()
    return "已清空本周数据，已备份历史"

# ======================
# 用户管理路由
# ======================
@app.route("/create_user", methods=["POST"])
@role_required("admin")
def create_user():
    """
    创建新用户 - 添加操作员或审核员用户
    """
    username = request.form["username"]
    password = request.form["password"]
    role = request.form["role"]

    # 验证角色
    if role not in ["operator", "reviewer"]:
        return "非法角色"

    # 检查用户名是否已存在
    if User.query.filter_by(username=username).first():
        return "用户名已存在"

    # 创建用户
    db.session.add(User(username=username, password=password, role=role))
    db.session.commit()

    return redirect("/admin_home")

@app.route("/update_role/<int:user_id>", methods=["POST"])
@role_required("admin")
def update_role(user_id):
    """
    更新用户角色 - 修改指定用户的角色
    """
    user = User.query.get(user_id)
    if not user:
        return "用户不存在"

    if user.role == "admin":
        return "不能修改管理员"

    new_role = request.form.get("role")
    if new_role not in ["operator", "reviewer"]:
        return "非法角色"

    user.role = new_role
    db.session.commit()

    return redirect("/admin_home")

@app.route("/delete_user/<int:user_id>")
@role_required("admin")
def delete_user(user_id):
    """
    删除用户 - 移除指定用户（不能删除管理员）
    """
    user = User.query.get(user_id)
    if user.username == "admin":
        return "不能删除管理员"

    db.session.delete(user)
    db.session.commit()

    return redirect("/admin_home")

@app.route("/update_password/<int:user_id>", methods=["POST"])
@role_required("admin")
def update_password(user_id):
    """
    更新用户密码 - 修改指定用户的密码
    """
    user = User.query.get(user_id)

    if not user:
        return "用户不存在"

    # 禁止修改管理员密码
    if user.username == "admin":
        return "不能修改管理员密码"

    new_password = request.form.get("password")

    if not new_password:
        return "密码不能为空"

    user.password = new_password
    db.session.commit()

    return "修改成功"

# ======================
# 应用启动
# ======================
if __name__ == "__main__":
    # 初始化数据库
    init_db()
    # 启动 Flask 开发服务器
    app.run(debug=True)