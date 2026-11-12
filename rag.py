from pathlib import Path
from typing import List
from dotenv import load_dotenv
import os
import certifi

load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from pypdf import PdfReader
import docx2txt

# --- SaliBot upgrade: extra file types (Excel, PowerPoint, images) ---
import base64
import mimetypes
from openpyxl import load_workbook
from pptx import Presentation
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage


Path("uploads").mkdir(exist_ok=True)
Path("chroma_db").mkdir(exist_ok=True)


# Embeddings model
embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")

vectorstore = Chroma(
    collection_name="salibot_docs",
    embedding_function=embeddings,
    persist_directory="chroma_db"
)


# --- SaliBot upgrade: helpers for extra file types ---
IMAGE_TYPES = [".png", ".jpg", ".jpeg", ".webp"]


def read_excel_text(file_path: str) -> str:
    """Read every sheet of an Excel file as rows of text."""
    workbook = load_workbook(file_path, read_only=True, data_only=True)
    text = ""

    for sheet in workbook.worksheets:
        text += f"Sheet: {sheet.title}\n"

        for row in sheet.iter_rows(values_only=True):
            cells = [str(cell) for cell in row if cell is not None]
            if cells:
                text += " | ".join(cells) + "\n"

        text += "\n"

    workbook.close()
    return text


def read_pptx_text(file_path: str) -> str:
    """Read the text from every slide of a PowerPoint file."""
    presentation = Presentation(file_path)
    text = ""

    for number, slide in enumerate(presentation.slides, start=1):
        text += f"Slide {number}:\n"

        for shape in slide.shapes:
            if shape.has_text_frame:
                text += shape.text_frame.text + "\n"

            if shape.has_table:
                for row in shape.table.rows:
                    text += " | ".join(cell.text for cell in row.cells) + "\n"

        text += "\n"

    return text


def read_image_text(file_path: str) -> str:
    """Use Gemini vision to describe an image and copy any text in it."""
    mime_type = mimetypes.guess_type(file_path)[0] or "image/png"
    image_data = base64.b64encode(Path(file_path).read_bytes()).decode("utf-8")

    vision_llm = ChatGoogleGenerativeAI(
        model=os.getenv("GOOGLE_MODEL", "gemini-3.5-flash"),
        temperature=0
    )

    message = HumanMessage(content=[
        {
            "type": "text",
            "text": (
                "Describe this image in detail. "
                "Then copy out any text you can see in it exactly as written."
            )
        },
        {
            "type": "image_url",
            "image_url": f"data:{mime_type};base64,{image_data}"
        }
    ])

    response = vision_llm.invoke([message])

    # Newer Gemini models may return a list of parts instead of plain text
    if isinstance(response.content, str):
        return response.content

    return "\n".join(
        part.get("text", "") if isinstance(part, dict) else str(part)
        for part in response.content
    )


def read_file_text(file_path: str) -> str:
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        reader = PdfReader(file_path)
        text = ""

        for page in reader.pages:
            text += page.extract_text() or ""
            text += "\n"

        return text

    if suffix == ".docx":
        return docx2txt.process(file_path)

    if suffix in [".txt", ".md", ".py", ".csv"]:
        return path.read_text(encoding="utf-8", errors="ignore")

    # --- SaliBot upgrade ---
    if suffix == ".xlsx":
        return read_excel_text(file_path)

    if suffix == ".pptx":
        return read_pptx_text(file_path)

    if suffix in IMAGE_TYPES:
        return read_image_text(file_path)

    raise ValueError(
        "Unsupported file type. Upload PDF, DOCX, TXT, MD, PY, CSV, "
        "XLSX, PPTX, or an image (PNG, JPG, JPEG, WEBP)."
    )


def add_document_to_rag(file_path: str, thread_id: str):
    text = read_file_text(file_path)

    if not text.strip():
        raise ValueError("No text could be extracted from this file.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=150
    )

    chunks = splitter.split_text(text)

    docs: List[Document] = [
        Document(
            page_content=chunk,
            metadata={
                "thread_id": thread_id,
                "source": Path(file_path).name
            }
        )
        for chunk in chunks
    ]

    vectorstore.add_documents(docs)

    return {
        "filename": Path(file_path).name,
        "chunks": len(docs)
    }


def retrieve_from_rag(query: str, thread_id: str, k: int = 4) -> str:
    docs = vectorstore.similarity_search(
        query,
        k=k,
        filter={"thread_id": thread_id}
    )

    if not docs:
        return "No relevant uploaded document content found."

    results = []

    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "uploaded document")
        results.append(
            f"[Source {i}: {source}]\n{doc.page_content}"
        )

    return "\n\n".join(results)
