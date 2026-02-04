"""FastAPI 메인 애플리케이션"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.config import settings
import logging

# 로깅 설정
logging.basicConfig(
    level=settings.log_level,
    format='[%(asctime)s] %(levelname)s [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title="쿠팡 도서 판매 자동화 시스템",
    description="교보문고 크롤링 + 쿠팡 자동 업로드 + 판매 분석",
    version="0.1.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """앱 시작 시 실행"""
    logger.info("애플리케이션 시작")

    # DB 초기화
    init_db()
    logger.info("데이터베이스 초기화 완료")


@app.on_event("shutdown")
async def shutdown_event():
    """앱 종료 시 실행"""
    logger.info("애플리케이션 종료")


@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "쿠팡 도서 판매 자동화 시스템",
        "version": "0.1.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """헬스 체크"""
    return {"status": "healthy"}


# API 라우터 등록 (나중에 추가)
# from app.api import products, listings, sales, tasks
# app.include_router(products.router)
# app.include_router(listings.router)
# app.include_router(sales.router)
# app.include_router(tasks.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
