class AuthUser {
  final String id;
  final String email;
  final String fullName;
  final String role;
  final String? officeId;
  final String? officeName;
  final bool emailVerified;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  const AuthUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.role,
    required this.officeId,
    required this.officeName,
    required this.emailVerified,
    required this.createdAt,
    required this.updatedAt,
  });

  factory AuthUser.fromJson(Map<String, dynamic> json) {
    return AuthUser(
      id: (json['id'] ?? '').toString(),
      email: (json['email'] ?? '').toString(),
      fullName: (json['full_name'] ?? '').toString(),
      role: (json['role'] ?? 'student').toString(),
      officeId: _nullableString(json['office_id']),
      officeName: _nullableString(json['office_name']),
      // Missing field (older backends) = treat as verified so we don't lock people out.
      emailVerified: json['email_verified'] != false,
      createdAt: _parseDate(json['created_at']),
      updatedAt: _parseDate(json['updated_at']),
    );
  }

  AuthUser copyWith({bool? emailVerified}) {
    return AuthUser(
      id: id,
      email: email,
      fullName: fullName,
      role: role,
      officeId: officeId,
      officeName: officeName,
      emailVerified: emailVerified ?? this.emailVerified,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );
  }
}

class AuthResponse {
  final String accessToken;
  final String tokenType;
  final AuthUser user;

  const AuthResponse({
    required this.accessToken,
    required this.tokenType,
    required this.user,
  });

  factory AuthResponse.fromJson(Map<String, dynamic> json) {
    final rawUser = json['user'];
    return AuthResponse(
      accessToken: (json['access_token'] ?? '').toString(),
      tokenType: (json['token_type'] ?? 'bearer').toString(),
      user: AuthUser.fromJson(
        rawUser is Map ? Map<String, dynamic>.from(rawUser) : const {},
      ),
    );
  }
}

class LoginRequest {
  final String email;
  final String password;

  const LoginRequest({required this.email, required this.password});

  Map<String, dynamic> toJson() {
    return {
      'email': email.trim(),
      'password': password,
    };
  }
}

class SignupRequest {
  final String fullName;
  final String email;
  final String password;
  final String role;
  final String? inviteCode;

  const SignupRequest({
    required this.fullName,
    required this.email,
    required this.password,
    this.role = 'student',
    this.inviteCode,
  });

  Map<String, dynamic> toJson() {
    final code = inviteCode?.trim();
    return {
      'full_name': fullName.trim(),
      'email': email.trim(),
      'password': password,
      'role': role,
      if (code != null && code.isNotEmpty) 'invite_code': code,
    };
  }
}

class ChangePasswordRequest {
  final String currentPassword;
  final String newPassword;

  const ChangePasswordRequest({
    required this.currentPassword,
    required this.newPassword,
  });

  Map<String, dynamic> toJson() {
    return {
      'current_password': currentPassword,
      'new_password': newPassword,
    };
  }
}

String? _nullableString(Object? value) {
  final text = value?.toString().trim() ?? '';
  return text.isEmpty || text == 'null' ? null : text;
}

DateTime? _parseDate(Object? value) {
  final text = value?.toString().trim() ?? '';
  if (text.isEmpty || text == 'null') return null;
  return DateTime.tryParse(text)?.toLocal();
}
