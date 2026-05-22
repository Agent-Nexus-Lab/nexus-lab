from fastapi import FastAPI
from routers import profile, agent, plans, admin

app = FastAPI()

# 注册路由
app.include_router(profile.router)
app.include_router(agent.router)
app.include_router(plans.router)
app.include_router(admin.router)

@app.get("/")
def health_check():
    return {"code": 0, "message": "service is running"}