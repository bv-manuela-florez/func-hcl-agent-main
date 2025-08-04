import uuid
from typing import Any, List, Optional, Tuple
import os
import azure.cosmos.documents as documents
from azure.cosmos.container import ContainerProxy
from azure.cosmos import CosmosClient, DatabaseProxy
from pydantic import Field
from pydantic.main import BaseModel as PydanticModel
from pydantic._internal._model_construction import ModelMetaclass as PydanticMetaclass
from cosmos_utils.telemetry import logger

# Set UTF-8 encoding for Windows to handle Unicode characters
if os.name == 'nt':  # Windows
    import sys
    if hasattr(sys, '_setdefaultencoding'):
        sys._setdefaultencoding('utf-8')
    # Set environment variable to ensure UTF-8 encoding
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

class TooManyObjectsFound(Exception):
    pass


class NoObjectFound(Exception):
    pass


def _get_client(obj):
    logger.debug("⬆️ Initializing CosmosDBClient")
    return CosmosClient(os.getenv('AZURE_COSMOS_DB_URI'), os.getenv('AZURE_COSMOS_DB_KEY'))
    # await app._cosmos_client.__aenter__()


def _get_or_create_database(obj) -> DatabaseProxy:
    # Asegura que el cliente esté inicializado
    if not hasattr(obj._meta, "client") or obj._meta.client is None:
        from azure.cosmos import CosmosClient
        obj._meta.client = CosmosClient(
            os.getenv('AZURE_COSMOS_DB_URI'),
            os.getenv('AZURE_COSMOS_DB_KEY')
        )
    return obj._meta.client.create_database_if_not_exists(os.getenv("AZURE_COSMOS_DB_NAME"))


def _get_or_create_container(obj) -> ContainerProxy:
    # Asegura que el atributo database esté inicializado
    if not hasattr(obj._meta, "database") or obj._meta.database is None:
        setattr(obj._meta, "database", _get_or_create_database(obj))
    if os.getenv("AZURE_COSMOS_DB_CONTAINER") is None:
        logger.error("❌ Container name is required")
        raise ValueError("Container name is required")
    return obj._meta.database.create_container_if_not_exists(
        obj._meta.container_name,
        {
            "paths": [f"/{obj._meta.partition_key}"],  # Aquí se usa "session_id"
            "kind": documents.PartitionKind.Hash,
        },
    )


def instance_connection(func):
    def wrapper(obj):
        if not hasattr(obj._meta, "client"):
            setattr(obj._meta, "client", _get_client(obj))

        if not hasattr(obj._meta, "database"):
            setattr(obj._meta, "database", _get_or_create_database(obj))

        if not hasattr(obj._meta, "container"):
            setattr(obj._meta, "container", _get_or_create_container(obj))

        return func(obj)

    return wrapper


def class_connection(func):
    def wrapper(cls, **kwargs):
        if not hasattr(cls.Meta, "client"):
            client = _get_client(cls)
            setattr(cls.Meta, "client", client)

        if not hasattr(cls.Meta, "database"):
            setattr(cls.Meta, "database", _get_or_create_database(cls))

        if not hasattr(cls.Meta, "container"):
            setattr(cls.Meta, "container", _get_or_create_container(cls))

        return func(cls, **kwargs)

    return wrapper


class BaseQuery:
    def get(self, **kwargs):
        pass

    def filter(self, **kwargs):
        pass


class Metaclass(PydanticMetaclass):
    def __new__(mcs, name, bases, namespace, **kwargs):
        super_new = super().__new__

        parents = [b for b in bases if isinstance(b, Metaclass)]
        if not parents:
            return super_new(mcs, name, bases, namespace)

        module = namespace.pop("__module__")
        namespace.update({"__module__": module})
        classcell = namespace.pop("__classcell__", None)
        if classcell is not None:
            namespace.update({"__classcell__": classcell})
        attr_meta = namespace.pop("Meta", None)
        new_class = super_new(mcs, name, bases, namespace, **kwargs)
        meta = attr_meta or getattr(new_class, "Meta", None)
        base_meta = getattr(new_class, "_meta", None)

        setattr(new_class, "_meta", meta)

        # Solo intenta copiar atributos si base_meta existe
        if base_meta is not None:
            if not hasattr(meta, "id_attr"):
                new_class._meta.id_attr = base_meta.id_attr

            if not hasattr(meta, "partition_key"):
                new_class._meta.partition_key = base_meta.partition_key

            if not hasattr(meta, "container_name"):
                new_class._meta.container_name = new_class.__name__

        return new_class


def uuid_factory():
    return str(uuid.uuid4())


class Queryset:
    pass


class CosmosModel(PydanticModel, metaclass=Metaclass):
    id: str = Field(default_factory=uuid_factory)
    rid: Optional[str] = Field(None, alias="_rid")
    self: Optional[str] = Field(None, alias="_self")
    etag: Optional[str] = Field(None, alias="_etag")
    attachments: Optional[str] = Field(None, alias="_attachments")
    ts: Optional[int] = Field(None, alias="_ts")

    __exclude_repr_args__ = ["rid", "self", "etag", "attachments", "ts"]

    class Meta:
        container_name: str
        id_attr: str = "id"
        partition_key: str = "id"

    def __repr_args__(self) -> Tuple[str, Any]:
        original_args = super().__repr_args__()
        args: List[Tuple[str, Any]] = []
        for key, value in original_args:
            if key not in self.__exclude_repr_args__:
                args.append((key, value))
        return args

    @instance_connection
    def save(self):
        try:
            # Get the data to save
            data = self.model_dump(by_alias=True)
            
            # Upsert the item to Cosmos DB
            upserted = self._meta.container.upsert_item(data)
            
            # Use logger instead of print to avoid encoding issues
            logger.info(f"Successfully saved item with ID: {upserted.get('id', 'unknown')}")
            self.model_validate(upserted)
            return self
        except Exception as e:
            logger.error(f"Error saving to Cosmos DB: {str(e)}")
            # If there's an encoding error, try with cleaned data
            if "codec" in str(e) or "charmap" in str(e):
                logger.warning("Retrying save with Unicode character cleaning...")
                data = self._clean_unicode_data(self.model_dump(by_alias=True))
                upserted = self._meta.container.upsert_item(data)
                logger.info(f"Successfully saved item with cleaned data, ID: {upserted.get('id', 'unknown')}")
                self.model_validate(upserted)
                return self
            else:
                raise
    
    def _clean_unicode_data(self, data):
        """Recursively clean Unicode characters that might cause encoding issues."""
        if isinstance(data, dict):
            return {key: self._clean_unicode_data(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._clean_unicode_data(item) for item in data]
        elif isinstance(data, str):
            # Handle Unicode characters more robustly
            try:
                # First, ensure the string is properly encoded as UTF-8
                # This should work for most cases including emojis
                return data.encode('utf-8', errors='replace').decode('utf-8')
            except Exception:
                # If there's still an issue, fall back to ASCII with replacement
                try:
                    return data.encode('ascii', errors='replace').decode('ascii')
                except Exception:
                    # Last resort: return a safe string
                    return "[content with special characters]"
        else:
            return data

    @classmethod
    @class_connection
    def all(cls):
        # TODO: should return queryset
        results = cls.Meta.container.read_all_items()
        results = list(results)
        return list(cls(**r) for r in results)

    @classmethod
    @class_connection
    def get(cls, **kwargs):
        # No forzar user_id, solo usar lo que recibe
        params = cls.__parse_to_dot_notation(kwargs)
        params = cls.__format_for_str_values(params)
        params_str = cls.__prepare_params_str(params)

        query_str = f"SELECT * FROM c WHERE {params_str}"

        results = cls.Meta.container.query_items(
            query=query_str,
            enable_cross_partition_query=True,
        )
        results = list(results)

        if not results:
            raise NoObjectFound

        if len(results) > 1:
            raise TooManyObjectsFound

        return cls(**results[0])

    @classmethod
    @class_connection
    def query(cls, **kwargs):
        # No forzar user_id, solo usar lo que recibe
        params = cls.__parse_to_dot_notation(kwargs)
        params = cls.__format_for_str_values(params)
        params_str = cls.__prepare_params_str(params)

        query_str = f"SELECT * FROM c WHERE {params_str}"

        results = cls.Meta.container.query_items(
            query=query_str,
            enable_cross_partition_query=True,
        )

        return list(cls(**r) for r in results)

    @staticmethod
    def __prepare_params_str(params):
        return " AND ".join([f"c.{k} = {v}" for k, v in params.items()])

    @staticmethod
    def __parse_to_dot_notation(params):
        return {key.replace("__", "."): params[key] for key in params}

    @staticmethod
    def __format_for_str_values(params):
        for key in params:
            if isinstance(params[key], str):
                params[key] = f'"{params[key]}"'
        return params

    @instance_connection
    def delete(self):
        self._meta.container.delete_item(self.id, partition_key=self.id)
