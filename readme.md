# 🚀 WooCommerce ➜ Shopify Order Uploader

This repository contains a **single purpose** Python script – `scripts/load.py` – that uploads WooCommerce orders to Shopify using the Shopify Admin REST API. All other migration helpers, exporters and logs have been removed so the codebase stays lean, dependency-light and, most importantly, **free of any credentials**.

---
## ✨ Key Features

- 🔄 **Status-aware uploads** – maps WooCommerce payment statuses to Shopify equivalents.
- 🕗 **Resume support** – safely restart large migrations without duplicating orders.
- 🧪 **Test mode** – create dummy orders with test e-mails before running a full upload.
- 🐌 **Smart rate-limit handling** – automatic back-off & retry logic keeps you within Shopify API limits.
- 🔒 **Zero hard-coded secrets** – credentials are only read from your local `.env` file.

---
## 📦 Folder Structure

```
Shopify-Migration-Tool/
├── data/                       # Place exported WooCommerce JSON here (git-ignored)
│   └── shopify_orders_ready.json
├── scripts/
│   └── load.py                # The order upload tool
├── .env                        # Your private credentials (never committed)
├── requirements.txt
└── README.md                   # (this file)
```

---
## 🛠️ Setup

1. **Clone & create a virtual env**
   ```bash
   git clone <your-repo-url>.git
   cd Shopify-Migration-Tool
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Add Shopify credentials** – create a `.env` file in the project root:
   ```env
   SHOPIFY_API_KEY=your_private_app_api_key
   SHOPIFY_ADMIN_API_ACCESS_TOKEN=shpat_your_admin_token
   SHOPIFY_STORE=your-store.myshopify.com
   ```

3. **Export WooCommerce orders** – generate `shopify_orders_ready.json` with your preferred method and place it inside the `data/` folder. (Any structure created by the removed exporter script is still accepted.)

4. **Run the uploader**
   ```bash
   python scripts/load.py
   ```
   Follow the interactive prompts to run either a **test** (10 dummy orders) or a **full** upload. You can safely resume interrupted uploads – progress is tracked in `data/upload_progress.json` (git-ignored).

---
## 🤝 Contributing
This repo is now purposely minimal. Feel free to open issues or PRs for bug fixes, but please keep feature additions tightly scoped.

---
## 📝 License
Released under the MIT License.
