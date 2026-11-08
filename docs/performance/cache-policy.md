# Region response revalidation

The mutable map index and genre lexicon use `Cache-Control: no-cache`: HTTP
caches may store them but must revalidate before reuse. A fresh shared-cache
lifetime would delay curator edits, so neither response uses a public max-age
or stale-while-revalidate allowance. Artist trees keep their existing no-store
policy.

The map index validator includes its snapshot checksum and content encoding.
The lexicon validator includes a representation version, snapshot checksum and
genre tree token. Matching validators return 304 before loading a stored payload
or serializing JSON; a new snapshot or any genre/playlist write invalidates the
validator. Both 200 and 304 carry the same ETag and cache policy. The one-hour
server-side payload TTL is bounded by the versioned cache key and does not
permit serving an older tree version.

Client query freshness is a separate policy. The shared lexicon hook currently
keeps an already loaded lexicon for its query lifetime; applications needing live
curator updates must invalidate that query. HTTP revalidation does not override
a client that makes no request.
