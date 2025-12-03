# EmoGo 資料後端服務 (FastAPI + MongoDB)

## 專案目標:

這是一個公開存取的後端資料頁面，用於呈現EmoGo前端收集到的三類數據：Vlog 影片、情緒分數及 GPS 座標。

## 資料下載頁面URI:

* 檢視資料頁面: https://emogo-backend-yu-hsuan-ho.onrender.com/data-download
* 直接下載CSV: https://emogo-backend-yu-hsuan-ho.onrender.com/download-csv

## 技術架構:

* API 框架: FastAPI (Python)
* 資料庫: MongoDB Atlas (使用 motor 驅動程式)
* 數據導出: 頁面包含「一鍵下載所有數據 (.CSV)」功能。