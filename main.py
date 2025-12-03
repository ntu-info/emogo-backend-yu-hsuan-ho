from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
from datetime import datetime
from bson import ObjectId

# --- 1. CONFIGURATION AND INITIALIZATION ---

# 請在 Render 上設定 MONGODB_URI 環境變數
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/")
DATABASE_NAME = "emogo"
COLLECTION_NAME = "datacsv" # 確保與您在 Compass 中建立的 Collection 名稱一致

app = FastAPI(
    title="EmoGo Public Data Backend (Updated)",
    description="FastAPI service for serving EmoGo data (Vlogs, Sentiments, GPS) from MongoDB.",
    version="1.0.1"
)

# 定義情緒代碼到顯示文字和顏色的映射 (繁體中文/英文)
# 請根據您的 EmoGo 專案定義，這裡假設 4 為「快樂」
SENTIMENT_MAPPING: Dict[int, tuple[str, str]] = {
    1: ("焦慮/Anxiety", "text-red-600"),
    2: ("悲傷/Sadness", "text-blue-600"),
    3: ("平靜/Calm", "text-gray-600"),
    4: ("快樂/Joy", "text-green-600"),
    5: ("興奮/Excited", "text-yellow-600"),
}

client: Optional[AsyncIOMotorClient] = None
db = None

@app.on_event("startup")
async def startup_db_client():
    """連接 MongoDB."""
    global client, db
    try:
        print(f"Connecting to MongoDB at URI: {MONGODB_URI[:30]}...")
        client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        await client.admin.command('ping')
        db = client[DATABASE_NAME]
        print("Successfully connected to MongoDB!")
    except Exception as e:
        print(f"Error connecting to MongoDB: {e}")
        pass

@app.on_event("shutdown")
async def shutdown_db_client():
    """關閉 MongoDB 連線."""
    if client:
        client.close()
        print("MongoDB connection closed.")


# --- 2. DATA MODELS (匹配您在 Compass 中的扁平化結構) ---

class MongoDBItem(BaseModel):
    """反映使用者 MongoDB 文件中的欄位。"""
    id: Optional[str] = Field(None, alias="_id") # MongoDB ID
    timestamp: str # 儲存為字串
    sentiment: int # 儲存為整數代碼 (e.g., 4)
    vlog_path: str # 影片連結/URI
    lat: float # 緯度
    lng: float # 經度
    
    # 由於您的範例中沒有 user_id，我們設為可選，但在渲染時會使用預設值
    user_id: Optional[str] = None 
    
    # 忽略範例中看似冗餘的 'id' 欄位
    
    class Config:
        populate_by_name = True
        extra = 'ignore' # 忽略其他未定義的欄位

# --- 3. API ENDPOINTS ---

@app.get("/")
async def root():
    """根目錄健康檢查。"""
    return {"message": "EmoGo Backend is running. Check /data-download for public data."}

@app.get("/data-download", response_class=HTMLResponse)
async def data_download_page():
    """
    產生並返回用於查看和下載 EmoGo 資料的公開 HTML 頁面。
    """
    if db is None:
        return HTMLResponse("<h1>錯誤: 資料庫連線失敗。請檢查 MONGODB_URI 環境變數。</h1>", status_code=503)

    data_items: List[MongoDBItem] = []
    
    try:
        # 獲取最新的 10 筆資料
        cursor = db[COLLECTION_NAME].find().sort("timestamp", -1).limit(10)
        async for doc in cursor:
            # motor 驅動程式會自動將 $numberDouble/$numberInt 轉換為 Python float/int
            # 處理 _id 欄位
            doc['id'] = str(doc.pop('_id'))
            
            # 使用 Pydantic 進行資料驗證和型別轉換
            data_items.append(MongoDBItem(**doc))
        
    except Exception as e:
        print(f"Error fetching data from MongoDB: {e}")
        error_html = f"""
        <div class="p-6 bg-red-100 border-l-4 border-red-500 text-red-700">
            <p class="font-bold">資料庫錯誤 (Database Error)</p>
            <p>無法載入資料。請檢查 MongoDB 連線狀態和 Collection 名稱是否正確。</p>
            <p class="text-xs mt-2">詳細錯誤: {e}</p>
        </div>
        """
        return HTMLResponse(get_html_template(error_html), status_code=500)


    # --- HTML 渲染邏輯 ---

    data_rows_html = ""
    for item in data_items:
        # 1. 影片連結
        # 由於您使用的是 Google Drive 連結，我將保持其原樣，但提醒它需要公開權限
        mock_video_link = (
            f"<a href='{item.vlog_path}' "
            "download='vlog_{item.id}.mp4' "
            "class='text-blue-500 hover:text-blue-700 font-medium' "
            "target='_blank'>下載/播放 (Download/Play)</a>"
        )
        
        # 2. 情緒代碼轉換
        emotion_tuple = SENTIMENT_MAPPING.get(item.sentiment, ("未知/Unknown", "text-gray-400"))
        emotion_text = emotion_tuple[0]
        sentiment_color = emotion_tuple[1]
        
        # 3. 時間戳記格式化
        try:
            # 嘗試解析使用者提供的字串格式: "2025-11-2707:35:33"
            dt_obj = datetime.strptime(item.timestamp, '%Y-%m-%d%H:%M:%S')
            formatted_timestamp = dt_obj.strftime('%Y/%m/%d %H:%M:%S')
        except ValueError:
            formatted_timestamp = item.timestamp + " (格式錯誤)" # 格式化失敗時顯示原始字串
            
        # 4. 處理 User ID
        user_display = item.user_id or 'anonymous (匿名)'
        
        # 5. GPS Placeholder
        city_placeholder = "N/A (請在資料庫中加入城市名稱欄位)"


        data_rows_html += f"""
        <tr class="border-b hover:bg-gray-50">
            <td class="px-4 py-3 text-sm font-medium text-gray-900">{user_display}</td>
            <td class="px-4 py-3 text-sm text-gray-500">{formatted_timestamp}</td>
            <td class="px-4 py-3 text-sm text-gray-900">
                <span class="font-semibold {sentiment_color}">{emotion_text}</span> ({item.sentiment} / Score N/A)
            </td>
            <td class="px-4 py-3 text-sm text-gray-500">
                Lat: {item.lat:.6f}, Lng: {item.lng:.6f} ({city_placeholder})
            </td>
            <td class="px-4 py-3 text-sm font-mono text-gray-700">
                {mock_video_link}
                <div class="text-xs text-gray-400 mt-1">（檔案路徑）</div>
            </td>
        </tr>
        """

    if not data_items:
        data_rows_html = """
        <tr>
            <td colspan="5" class="px-4 py-12 text-center text-gray-500 text-lg">
                <p>在 'emogo_data' Collection 中未找到資料。</p>
                <p class="mt-2 text-sm">請使用 MongoDB Compass 確認資料已成功插入。</p>
            </td>
        </tr>
        """

    content = f"""
    <div class="max-w-7xl mx-auto p-4 sm:p-6 lg:p-8">
        <header class="mb-8 p-6 bg-blue-600 rounded-xl shadow-lg">
            <h1 class="text-4xl font-extrabold text-white">EmoGo 資料下載門戶 (Data Download Portal)</h1>
            <p class="mt-2 text-xl text-blue-200">公開存取最新的 EmoGo 收集資料。</p>
            <p class="mt-2 text-sm text-blue-300">目前顯示 {len(data_items)} 筆資料。</p>
        </header>
        
        <div class="bg-white shadow-xl rounded-xl overflow-hidden">
            <div class="p-6 bg-gray-50 border-b border-gray-200">
                <h2 class="text-2xl font-semibold text-gray-800">最新收集資料列表</h2>
            </div>
            
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-100">
                        <tr>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">使用者 ID (User ID)</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">時間戳記 (Timestamp)</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">情緒 (Sentiment)</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">GPS 座標 (GPS Coords)</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Vlog 影片 (Video)</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {data_rows_html}
                    </tbody>
                </table>
            </div>
        </div>
        
        <footer class="mt-10 pt-6 border-t border-gray-200 text-center text-sm text-gray-500">
            <p>&copy; {datetime.now().year} EmoGo Backend. Powered by FastAPI and MongoDB.</p>
        </footer>
    </div>
    """
    
    return HTMLResponse(content=get_html_template(content))

# --- 4. HTML Template Function ---

def get_html_template(content: str) -> str:
    """提供帶有 Tailwind CSS 的完整 HTML 包裝器。"""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EmoGo Data Download</title>
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{
            font-family: 'Inter', sans-serif;
            background-color: #f3f4f6;
        }}
        /* Ensure responsive table behavior */
        @media (max-width: 640px) {{
            table, thead, tbody, th, td, tr {{
                display: block;
            }}
            thead tr {{
                position: absolute;
                top: -9999px;
                left: -9999px;
            }}
            tr {{ border: 1px solid #ccc; margin-bottom: 0.5rem; }}
            td {{
                border: none;
                border-bottom: 1px solid #eee;
                position: relative;
                padding-left: 50%;
                text-align: right;
            }}
            td::before {{
                position: absolute;
                top: 0;
                left: 6px;
                width: 45%;
                padding-right: 10px;
                white-space: nowrap;
                text-align: left;
                font-weight: 600;
                color: #4b5563;
            }}
            /* Labels for small screen */
            td:nth-of-type(1)::before {{ content: "User ID"; }}
            td:nth-of-type(2)::before {{ content: "Timestamp"; }}
            td:nth-of-type(3)::before {{ content: "Sentiment"; }}
            td:nth-of-type(4)::before {{ content: "GPS Coords"; }}
            td:nth-of-type(5)::before {{ content: "Video (Download)"; }}
        }}
    </style>
</head>
<body>
    {content}
</body>
</html>
"""