from fastapi import FastAPI
from routers import profile, agent, plans, admin
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(profile.router)
app.include_router(agent.router)
app.include_router(plans.router)
app.include_router(admin.router)

@app.get("/")
def health_check():
    return {"code": 0, "message": "service is running"}
from database import Base, engine
Base.metadata.create_all(bind=engine)