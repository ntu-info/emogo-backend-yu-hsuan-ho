from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
from datetime import datetime
import io # 新增：用於處理 CSV 檔案流
import csv # 新增：用於 CSV 格式轉換
from bson import ObjectId

# --- 1. CONFIGURATION AND INITIALIZATION ---

# 請在 Render 上設定 MONGODB_URI 環境變數
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/")
DATABASE_NAME = "emogo"
COLLECTION_NAME = "datacsv" # 確保與您在 Compass 中建立的 Collection 名稱一致

app = FastAPI(
    title="EmoGo Public Data Backend (Updated)",
    description="FastAPI service for serving EmoGo data (Vlogs, Sentiments, GPS) from MongoDB.",
    version="1.0.2" # 版本號更新
)

# 定義情緒分數的顯示文字和顏色
SENTIMENT_MAPPING: Dict[int, tuple[str, str]] = {
    1: ("Bad", "text-red-600"),
    2: ("Poor", "text-orange-600"),
    3: ("Average", "text-yellow-600"),
    4: ("Good", "text-green-300"),
    5: ("Happy", "text-green-600"),
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


# --- 2. DATA MODELS (matching with Compass) ---

class MongoDBItem(BaseModel):
    """反映使用者 MongoDB 文件中的欄位。"""
    id: Optional[str] = Field(None, alias="_id") # MongoDB ID
    user_id: int #使用者ID
    timestamp: str # 儲存為字串
    sentiment: int # 儲存為整數代碼 (e.g., 4)
    vlog_path: str # 影片連結/URI
    lat: float # 緯度
    lng: float # 經度
    
    class Config:
        populate_by_name = True
        extra = 'ignore' # 忽略其他未定義的欄位

# --- 3. API ENDPOINTS ---

@app.get("/")
async def root():
    """根目錄健康檢查。"""
    return {"message": "EmoGo Backend is running. Check /data-download for public data."}


@app.get("/download-csv")
async def download_csv():
    """
    從 MongoDB 獲取所有數據，轉換為 CSV 格式並提供下載。
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection failed.")

    # CSV 的標頭 (欄位名稱)
    headers = [
        "Record_ID", "User_ID", "Timestamp", "Sentiment_Code", 
        "Sentiment_Text", "Latitude", "Longitude", "Vlog_Path"
    ]
    
    # 使用 io.StringIO 創建一個記憶體中的檔案緩衝區
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers) # 寫入標頭

    try:
        # 從資料庫中獲取所有數據 (為了下載，我們獲取所有數據，而不只是 10 筆)
        cursor = db[COLLECTION_NAME].find().sort("timestamp", -1)
        async for doc in cursor:
            # 1. 處理情緒代碼轉換
            emotion_tuple = SENTIMENT_MAPPING.get(doc.get('sentiment', 0), ("Unknown", ""))
            sentiment_text = emotion_tuple[0]
            
            # 2. 格式化時間戳記 (假設格式為 "2025-11-2707:35:33")
            timestamp_str = doc.get('timestamp', '')
            try:
                dt_obj = datetime.strptime(timestamp_str, '%Y-%m-%d%H:%M:%S')
                formatted_timestamp = dt_obj.strftime('%Y/%m/%d %H:%M:%S')
            except ValueError:
                formatted_timestamp = timestamp_str # 格式化失敗則使用原始字串

            # 3. 寫入一行資料
            row = [
                str(doc.get('_id')),
                doc.get('user_id', 'N/A'),
                formatted_timestamp,
                doc.get('sentiment', 0),
                sentiment_text,
                doc.get('lat', 'N/A'),
                doc.get('lng', 'N/A'),
                doc.get('vlog_path', 'N/A')
            ]
            writer.writerow(row)

    except Exception as e:
        print(f"Error generating CSV: {e}")
        raise HTTPException(status_code=500, detail="Error generating CSV file.")

    # 返回 StreamingResponse 觸發檔案下載
    response = StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv"
    )
    # 設定下載檔案名稱和編碼 (中文環境建議使用 utf-8-sig)
    filename = f"emogo_data_export_{datetime.now().strftime('%Y%m%d')}.csv"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    
    return response


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
        # 1. 影片連結(Google Drive 公開權限)
        mock_video_link = (
            f"<a href='{item.vlog_path}' "
            "download='vlog_{item.id}.mp4' "
            "class='text-blue-500 hover:text-blue-700 font-medium' "
            "target='_blank'> 檢視/下載 (See/Download)</a>"
        )
        
        # 2. 情緒分數顯示
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
        user_display = item.user_id # 您的資料結構中 user_id 為 int
        
        
        #表格內容:
        data_rows_html += f"""
        <tr class="border-b hover:bg-gray-50">
            <td class="px-4 py-3 text-sm font-medium text-gray-900">{user_display}</td>
            <td class="px-4 py-3 text-sm text-gray-500">{formatted_timestamp}</td>
            <td class="px-4 py-3 text-sm text-gray-900">
                <span class="font-semibold {sentiment_color}">{emotion_text}</span> ({item.sentiment})
            </td>
            <td class="px-4 py-3 text-sm text-gray-500">
                {item.lat:.6f}, {item.lng:.6f}
            </td>
            <td class="px-4 py-3 text-sm font-mono text-gray-700">
                {mock_video_link}
            </td>
        </tr>
        """

    if not data_items:
        data_rows_html = """
        <tr>
            <td colspan="5" class="px-4 py-12 text-center text-gray-500 text-lg">
                <p>在 'datacsv' Collection 中未找到資料。</p>
                <p class="mt-2 text-sm">請使用 MongoDB Compass 確認資料已成功插入。</p>
            </td>
        </tr>
        """
        # 如果沒有數據，隱藏下載按鈕
        download_button_html = ""
    else:
        # 下載按鈕 HTML，指向新的 /download-csv 路由
        download_button_html = f"""
        <div class="flex justify-end mb-4">
            <a href="/download-csv" class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-green-500 hover:bg-green-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 transition duration-150 ease-in-out">
                <!-- Lucide Download Cloud Icon -->
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mr-2"><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/><path d="m7 10 5 5 5-5"/><path d="M12 15V4"/></svg>
                一鍵下載所有數據 (.CSV)
            </a>
        </div>
        """
    
    content = f"""
    <div class="max-w-7xl mx-auto p-4 sm:p-6 lg:p-8">
        <header class="mb-8 p-6 bg-gray-600 rounded-xl shadow-lg">
            <h1 class="text-4xl font-extrabold text-white">EmoGo 資料下載網站 (Data Download Portal)</h1>
            <p class="mt-2 text-xl text-white">公開存取最新的 EmoGo 收集資料。</p>
            <p class="mt-2 text-sm text-white">目前顯示 {len(data_items)} 筆資料。</p>
        </header>
        
        {download_button_html} <!-- 放置下載按鈕 -->

        <div class="bg-white shadow-xl rounded-xl overflow-hidden">
            <div class="p-6 bg-gray-50 border-b border-gray-200">
                <h2 class="text-2xl font-semibold text-gray-800">最新收集資料列表 (Recent Data)</h2>
                <p class="text-sm text-gray-500">此列表僅顯示最新的 10 筆資料，但下載按鈕會匯出所有資料。</p>
            </div>
            
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-100">
                        <tr>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">使用者 ID User ID</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">時間戳記Timestamp (時區: UTC+8) </th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">情緒Sentiment(1-5分)</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">GPS 座標GPS Coords(緯度, 經度)</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">影片Video</th>
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