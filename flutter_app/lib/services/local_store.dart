import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'web_token_store.dart';

/// Cross-platform key/value persistence (web, mobile, desktop).
///
/// JWT storage:
/// - mobile/desktop: flutter_secure_storage when Remember me is on
/// - web + Remember me: localStorage (survives browser restart)
/// - web + Remember me off: sessionStorage (same tab only)
/// - Remember me off on mobile: in-memory only
class LocalStore {
  LocalStore._();

  static const _secureTokenKey = 'aska_access_token';
  static const _rememberMePrefKey = 'aska_remember_me_pref';

  static SharedPreferences? _prefs;
  static const FlutterSecureStorage _secure = FlutterSecureStorage();
  static String? _memoryToken;

  static Future<void> init() async {
    _prefs ??= await SharedPreferences.getInstance();
    if (kIsWeb) {
      // SharedPreferences on web is localStorage — keep JWT there for Remember me.
      // Do not migrate durable tokens into sessionStorage.
      return;
    }
    final legacy = _prefs!.getString(_secureTokenKey)?.trim();
    if (legacy != null && legacy.isNotEmpty) {
      await _secure.write(key: _secureTokenKey, value: legacy);
      await _prefs!.remove(_secureTokenKey);
    }
  }

  static SharedPreferences get instance {
    final prefs = _prefs;
    if (prefs == null) {
      throw StateError('LocalStore.init() must be called before use.');
    }
    return prefs;
  }

  static String? getString(String key) {
    if (key == _secureTokenKey) {
      return _memoryToken;
    }
    final value = instance.getString(key)?.trim();
    return value == null || value.isEmpty ? null : value;
  }

  static Future<String?> readSecureToken() async {
    if (_memoryToken != null && _memoryToken!.isNotEmpty) {
      return _memoryToken;
    }
    if (kIsWeb) {
      // Prefer durable Remember-me token, then tab session.
      final durable = await readWebLocalToken(_secureTokenKey);
      if (durable != null) return durable;
      return readWebSessionToken(_secureTokenKey);
    }
    final value = (await _secure.read(key: _secureTokenKey))?.trim();
    return value == null || value.isEmpty ? null : value;
  }

  /// True when the stored JWT is durable across browser/app restarts.
  static Future<bool> hasDurableAccessToken() async {
    if (kIsWeb) {
      final durable = await readWebLocalToken(_secureTokenKey);
      return durable != null && durable.isNotEmpty;
    }
    final value = (await _secure.read(key: _secureTokenKey))?.trim();
    return value != null && value.isNotEmpty;
  }

  /// User's last Remember me choice on the sign-in form (defaults to false).
  static bool getRememberMePreference() {
    return instance.getBool(_rememberMePrefKey) ?? false;
  }

  static Future<void> setRememberMePreference(bool value) {
    return instance.setBool(_rememberMePrefKey, value);
  }

  static Future<bool> setString(String key, String value) async {
    if (key == _secureTokenKey) {
      return storeAccessToken(value, persist: true);
    }
    return instance.setString(key, value);
  }

  /// Persist JWT when [persist] is true (Remember me); otherwise tab/session only.
  static Future<bool> storeAccessToken(
    String token, {
    required bool persist,
  }) async {
    final cleaned = token.trim();
    if (cleaned.isEmpty) return false;
    _memoryToken = cleaned;
    if (kIsWeb) {
      if (persist) {
        await writeWebLocalToken(_secureTokenKey, cleaned);
        await clearWebSessionToken(_secureTokenKey);
        await instance.remove(_secureTokenKey);
      } else {
        await writeWebSessionToken(_secureTokenKey, cleaned);
        await clearWebLocalToken(_secureTokenKey);
        await instance.remove(_secureTokenKey);
      }
      return true;
    }
    if (!persist) {
      await _secure.delete(key: _secureTokenKey);
      await instance.remove(_secureTokenKey);
      return true;
    }
    await _secure.write(key: _secureTokenKey, value: cleaned);
    await instance.remove(_secureTokenKey);
    return true;
  }

  static Future<bool> remove(String key) async {
    if (key == _secureTokenKey) {
      await clearAccessToken();
      return true;
    }
    return instance.remove(key);
  }

  static Future<void> clearAccessToken({bool clearMemory = true}) async {
    if (clearMemory) {
      _memoryToken = null;
    }
    if (kIsWeb) {
      await clearWebSessionToken(_secureTokenKey);
      await clearWebLocalToken(_secureTokenKey);
      await instance.remove(_secureTokenKey);
    } else {
      await _secure.delete(key: _secureTokenKey);
      await instance.remove(_secureTokenKey);
    }
  }
}
