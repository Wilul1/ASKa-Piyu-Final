import 'web_token_store_stub.dart'
    if (dart.library.html) 'web_token_store_web.dart' as impl;

Future<String?> readWebLocalToken(String key) => impl.readWebLocalToken(key);

Future<void> writeWebLocalToken(String key, String value) =>
    impl.writeWebLocalToken(key, value);

Future<void> clearWebLocalToken(String key) => impl.clearWebLocalToken(key);

Future<String?> readWebSessionToken(String key) => impl.readWebSessionToken(key);

Future<void> writeWebSessionToken(String key, String value) =>
    impl.writeWebSessionToken(key, value);

Future<void> clearWebSessionToken(String key) => impl.clearWebSessionToken(key);
