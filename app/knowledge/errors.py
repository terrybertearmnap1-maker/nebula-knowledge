"""Domain errors raised by the knowledge base."""


class KnowledgeBaseError(Exception):
    """Base class for expected knowledge-base failures."""


class TeamNotFound(KnowledgeBaseError):
    pass


class DocumentNotFound(KnowledgeBaseError):
    pass


class DuplicateDocument(KnowledgeBaseError):
    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        super().__init__(f"document already exists: {document_id}")


class UnsupportedFileType(KnowledgeBaseError):
    pass


class DocumentParseError(KnowledgeBaseError):
    pass
