# Supplier quote OCR and AI extraction

**Status:** Planned. Add **Upload Supplier Quote** to Market Intelligence so merchants can turn a Bangla or English screenshot into confirmed sourcing evidence.

## 1. Upload and preview

- Add the upload and review flow in [SourcingWorkspace.tsx](../../frontend/src/components/SourcingWorkspace.tsx) and use the existing [API client](../../frontend/src/lib/api.ts).
- Add authenticated preview and confirm routes to the [Sourcing API](../../backend/xenovarients/api/sourcing.py). Accept one PNG or JPEG per preview. Check decoded image format, file size, and pixel count. Run OCR in a bounded worker with a timeout. Stage the original image and candidate fields privately under the business and uploader, with an expiry for abandoned previews.
- Run Tesseract with Bangla and English language data. Retain text and line positions for review. Show a retry message for unreadable or empty results. [Tesseract language data](https://tesseract-ocr.github.io/tessdoc/Data-Files)

## 2. Extract and validate fields

- Add a sourcing extraction service that uses the existing [Ollama client](../../backend/xenovarients/platform/llm/client.py). Treat OCR text as untrusted input. Send only the text needed for extraction and mask irrelevant contact details. Request structured output and validate it with a Pydantic schema. [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- Return draft line items with product, unit price, currency, minimum order quantity, and lead time. Attach OCR line references and check that cited lines exist. Validate number ranges and currency codes. Preserve distinct price tiers and leave missing or ambiguous fields blank. Provide manual entry if OCR or extraction fails.
- Show the image, extracted fields, and supporting text in the review screen. Let the merchant correct fields and confirm the result. Never allow image text or model output to invoke tools or persist records.

## 3. Save confirmed supplier evidence

- Add a tenant-scoped supplier quote record in [sourcing models](../../backend/xenovarients/models/sourcing.py) and an Alembic migration. Store confirmed fields, source reference, timestamps, and who confirmed it. Keep supplier quotes separate from automated Daraz retail and Google Trends snapshots.
- Revalidate the edited payload at confirmation, enforce the business and uploader scope, and make confirmation idempotent. Use private storage for source images, limit retention, and keep raw images and OCR text out of logs.

## Acceptance checks

- A merchant uploads English, Bangla, and bilingual screenshots, verifies extracted fields against the image, and saves a quote.
- Missing prices, ambiguous currencies, quantity tiers, and blurry images produce reviewable drafts or clear fallbacks. The preview never writes a confirmed quote.
- Instructions embedded in images cannot trigger actions. An expired draft or a draft owned by another business cannot be accessed or confirmed. Retrying confirmation creates only one quote.
- Select **OCR** and **AI Extraction** in the submission after the full workflow passes these checks.
