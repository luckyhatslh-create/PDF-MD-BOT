"""
Embeddings Module - генерация векторных представлений для RAG

Поддерживаемые провайдеры:
- OpenAI (ada-002, text-embedding-3-small/large)
- Local (sentence-transformers) - без API ключей
- Ollama (локальные модели)
"""

from typing import Optional
from dataclasses import dataclass
import json


@dataclass
class EmbeddingConfig:
    """Конфигурация эмбеддингов"""
    provider: str = "openai"  # openai, local, ollama
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    batch_size: int = 100


class EmbeddingProvider:
    """Базовый класс для провайдеров эмбеддингов"""
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError
    
    def embed_single(self, text: str) -> list[float]:
        return self.embed([text])[0]


class OpenAIEmbeddings(EmbeddingProvider):
    """OpenAI эмбеддинги"""
    
    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("pip install openai")
        
        self.client = OpenAI(api_key=api_key)
        self.model = model
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        # Очищаем тексты
        texts = [t.replace("\n", " ").strip()[:8000] for t in texts]
        
        response = self.client.embeddings.create(
            model=self.model,
            input=texts
        )
        
        return [item.embedding for item in response.data]


class LocalEmbeddings(EmbeddingProvider):
    """Локальные эмбеддинги через sentence-transformers"""
    
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError("pip install sentence-transformers")
        
        self.model = SentenceTransformer(model_name)
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()


class OllamaEmbeddings(EmbeddingProvider):
    """Ollama локальные эмбеддинги"""
    
    def __init__(
        self, 
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434"
    ):
        self.model = model
        self.base_url = base_url
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        import requests
        
        embeddings = []
        for text in texts:
            response = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text}
            )
            embeddings.append(response.json()["embedding"])
        
        return embeddings


def get_embedding_provider(
    provider: str = "openai",
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> EmbeddingProvider:
    """
    Фабрика для создания провайдера эмбеддингов
    
    Args:
        provider: 'openai', 'local', 'ollama'
        api_key: API ключ (для OpenAI)
        model: Название модели
        
    Returns:
        Инстанс EmbeddingProvider
    """
    if provider == "openai":
        if not api_key:
            raise ValueError("OpenAI требует API ключ")
        return OpenAIEmbeddings(api_key, model or "text-embedding-3-small")
    
    elif provider == "local":
        return LocalEmbeddings(model or "intfloat/multilingual-e5-small")
    
    elif provider == "ollama":
        return OllamaEmbeddings(model or "nomic-embed-text")
    
    else:
        raise ValueError(f"Неизвестный провайдер: {provider}")


def generate_embeddings_for_chunks(
    chunks: list,
    provider: EmbeddingProvider,
    batch_size: int = 50
) -> list[list[float]]:
    """
    Генерация эмбеддингов для списка чанков
    
    Args:
        chunks: Список ParsedChunk
        provider: Провайдер эмбеддингов
        batch_size: Размер батча
        
    Returns:
        Список эмбеддингов в том же порядке
    """
    texts = [chunk.content for chunk in chunks]
    embeddings = []
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch_embeddings = provider.embed(batch)
        embeddings.extend(batch_embeddings)
        print(f"Processed {min(i + batch_size, len(texts))}/{len(texts)} chunks")
    
    return embeddings


if __name__ == "__main__":
    # Пример использования
    print("Embedding providers:")
    print("- OpenAI: requires OPENAI_API_KEY")
    print("- Local: pip install sentence-transformers")
    print("- Ollama: requires running Ollama server")
