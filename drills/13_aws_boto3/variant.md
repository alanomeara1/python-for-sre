# 13 · Variant: S3 bucket audit and stale objects

Same patterns as the main drill (injected client, paginators, `ClientError` codes), on S3, where
"the config doesn't exist" comes back as an error you must tell apart from a real failure.

## The task

> Security wants a report of every S3 bucket that isn't versioned, has no default encryption
> configured, or doesn't fully block public access. And while you're there: list objects under a
> prefix older than N days so we can check the lifecycle rules are actually working.

## Contract

```python
def audit_buckets(s3) -> dict[str, list[str]]
    # every bucket in the account -> its issues, in THIS order (empty list = clean):
    #   "versioning-disabled"        versioning Status is not "Enabled" (never enabled, or "Suspended")
    #   "no-default-encryption"      get_bucket_encryption raises ClientError code
    #                                "ServerSideEncryptionConfigurationNotFoundError"
    #   "public-access-not-blocked"  no public access block (ClientError code
    #                                "NoSuchPublicAccessBlockConfiguration"), OR any of its four flags is False
    # any OTHER ClientError (e.g. AccessDenied) must propagate. Don't report a bucket clean because you couldn't read it.
    # use the list_buckets paginator

def stale_objects(s3, bucket: str, prefix: str, older_than_days: int, now: datetime) -> list[dict]
    # objects under prefix with LastModified strictly before now - older_than_days
    # -> [{"key": str, "size": int, "last_modified": datetime}], sorted by (last_modified, key)
    # `now` is timezone-aware (LastModified is UTC-aware; comparing naive to aware raises TypeError)
    # use the list_objects_v2 paginator. A page with no matches has NO "Contents" key.
```

## Reality check (say this out loud)

- "Since January 2023 AWS applies SSE-S3 to every new bucket, so on real AWS `get_bucket_encryption`
  almost always succeeds with AES256. The meaningful production rule is usually 'not SSE-KMS with our
  key'. moto (5.2) still returns NotFound for new buckets, which is why this drill tests that code path."
- "`now` is a parameter, not `datetime.now()` inside the function, so the test controls time and the
  function is deterministic."
- "Distinguishing 'config not found' from 'access denied' is the whole game. An audit that reports
  unreadable buckets as clean is worse than no audit."
- "At scale I wouldn't list objects at all. S3 Inventory plus Athena, or Storage Lens, is cheaper
  and faster than ListObjectsV2 over a billion keys."
