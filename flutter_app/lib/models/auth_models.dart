class AuthUser {
  final String id;
  final String email;
  final String fullName;
  final String role;
  final String? officeId;
  final String? officeName;
  final String? studentId;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  const AuthUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.role,
    required this.officeId,
    required this.officeName,
    required this.studentId,
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
      studentId: _nullableString(json['student_id']),
      createdAt: _parseDate(json['created_at']),
      updatedAt: _parseDate(json['updated_at']),
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
  final String? studentId;
  final String password;

  const SignupRequest({
    required this.fullName,
    required this.email,
    required this.studentId,
    required this.password,
  });

  Map<String, dynamic> toJson() {
    return {
      'full_name': fullName.trim(),
      'email': email.trim(),
      'student_id': studentId?.trim(),
      'password': password,
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
