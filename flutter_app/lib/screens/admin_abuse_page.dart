import 'dart:convert';

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../services/api_client.dart';
import '../widgets/sidebar.dart';
import '../widgets/student_ui.dart';
import 'admin_scaffold.dart';

/// Admin review of signup / failed-login velocity by IP.
class AdminAbuseDetectionPage extends StatefulWidget {
  const AdminAbuseDetectionPage({super.key});

  @override
  State<AdminAbuseDetectionPage> createState() =>
      _AdminAbuseDetectionPageState();
}

class _AdminAbuseDetectionPageState extends State<AdminAbuseDetectionPage> {
  bool _loading = false;
  String? _error;
  List<_AbuseFlag> _flags = const [];
  List<_AuthEventRow> _events = const [];
  String? _selectedIp;
  bool _requestedInitialLoad = false;
  String? _busyUserId;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (auth.role == 'admin' && !_requestedInitialLoad) {
      _requestedInitialLoad = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _load();
      });
    }
  }

  Future<void> _load({String? focusIp}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final flags = await _fetchFlags(context);
      if (!mounted) return;
      final ip = focusIp ??
          _selectedIp ??
          (flags.isNotEmpty ? flags.first.ipAddress : null);
      final events = await _fetchEvents(context, ip: ip);
      if (!mounted) return;
      setState(() {
        _flags = flags;
        _events = events;
        _selectedIp = ip;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _selectIp(String ip) async {
    setState(() => _selectedIp = ip);
    await _load(focusIp: ip);
  }

  Future<void> _toggleUserActive(_RelatedUser user) async {
    setState(() => _busyUserId = user.id);
    try {
      await _setUserActive(context, userId: user.id, isActive: !user.isActive);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            user.isActive
                ? 'Disabled ${user.email}'
                : 'Re-enabled ${user.email}',
          ),
        ),
      );
      await _load(focusIp: _selectedIp);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_friendlyError(error))),
      );
    } finally {
      if (mounted) setState(() => _busyUserId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AdminScaffold(
      current: StudentNavItem.adminAbuseDetection,
      title: 'Abuse Detection',
      description:
          'Review suspicious signup and login activity by IP. Flags are for admin review — disable accounts only when needed.',
      actions: [
        IconButton(
          tooltip: 'Refresh',
          onPressed: _loading ? null : () => _load(focusIp: _selectedIp),
          icon: const Icon(Icons.refresh_rounded),
        ),
      ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_loading) const LinearProgressIndicator(minHeight: 3),
          if (_error != null) ...[
            const SizedBox(height: 12),
            StudentPanel(
              padding: const EdgeInsets.all(14),
              child: Text(
                _error!,
                style: const TextStyle(color: DesignTokens.muted),
              ),
            ),
          ],
          const SizedBox(height: 16),
          Text(
            _flags.isEmpty
                ? 'No active abuse flags'
                : '${_flags.length} active flag${_flags.length == 1 ? '' : 's'}',
            style: const TextStyle(
              fontWeight: FontWeight.w900,
              fontSize: 16,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Signup: 5+ from one IP in 24 hours. Failed login: 15+ from one IP in 1 hour.',
            style: TextStyle(color: DesignTokens.muted, fontSize: 13),
          ),
          const SizedBox(height: 14),
          if (!_loading && _flags.isEmpty)
            const StudentPanel(
              padding: EdgeInsets.all(18),
              child: Text(
                'No suspicious patterns right now. Recent auth events still appear below when an IP is selected.',
                style: TextStyle(color: DesignTokens.muted, height: 1.4),
              ),
            )
          else
            ..._flags.map(
              (flag) => _AbuseFlagCard(
                flag: flag,
                selected: flag.ipAddress == _selectedIp,
                busyUserId: _busyUserId,
                onSelectIp: () => _selectIp(flag.ipAddress),
                onToggleUser: _toggleUserActive,
              ),
            ),
          const SizedBox(height: 22),
          Text(
            _selectedIp == null
                ? 'Recent auth events'
                : 'Recent events for $_selectedIp',
            style: const TextStyle(
              fontWeight: FontWeight.w900,
              fontSize: 16,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 12),
          if (_events.isEmpty)
            const Text(
              'No events for this filter yet.',
              style: TextStyle(color: DesignTokens.muted),
            )
          else
            ..._events.map((event) => _EventTile(event: event)),
        ],
      ),
    );
  }
}

class _AbuseFlagCard extends StatelessWidget {
  final _AbuseFlag flag;
  final bool selected;
  final String? busyUserId;
  final VoidCallback onSelectIp;
  final Future<void> Function(_RelatedUser user) onToggleUser;

  const _AbuseFlagCard({
    required this.flag,
    required this.selected,
    required this.busyUserId,
    required this.onSelectIp,
    required this.onToggleUser,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: selected ? DesignTokens.maroon : DesignTokens.border,
          width: selected ? 1.5 : 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: DesignTokens.maroon.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  flag.kind == 'signup_velocity'
                      ? 'SIGNUP BURST'
                      : 'LOGIN FAILURES',
                  style: const TextStyle(
                    color: DesignTokens.maroon,
                    fontWeight: FontWeight.w800,
                    fontSize: 11,
                  ),
                ),
              ),
              const Spacer(),
              TextButton(
                onPressed: onSelectIp,
                child: const Text('View events'),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            flag.reason,
            style: const TextStyle(
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'IP ${flag.ipAddress} · ${flag.count} events · last ${flag.latestAt}',
            style: const TextStyle(color: DesignTokens.muted, fontSize: 12.5),
          ),
          if (flag.relatedUsers.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text(
              'Related accounts',
              style: TextStyle(
                fontWeight: FontWeight.w800,
                fontSize: 13,
                color: DesignTokens.ink,
              ),
            ),
            const SizedBox(height: 8),
            ...flag.relatedUsers.map(
              (user) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            user.fullName,
                            style: const TextStyle(
                              fontWeight: FontWeight.w700,
                              color: DesignTokens.ink,
                            ),
                          ),
                          Text(
                            '${user.email} · ${user.role}${user.isActive ? '' : ' · disabled'}',
                            style: const TextStyle(
                              color: DesignTokens.muted,
                              fontSize: 12.5,
                            ),
                          ),
                        ],
                      ),
                    ),
                    TextButton(
                      onPressed: busyUserId == user.id
                          ? null
                          : () => onToggleUser(user),
                      child: Text(user.isActive ? 'Disable' : 'Enable'),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _EventTile extends StatelessWidget {
  final _AuthEventRow event;

  const _EventTile({required this.event});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Row(
        children: [
          Icon(
            event.eventType == 'signup'
                ? Icons.person_add_alt_1_rounded
                : event.eventType == 'login_ok'
                    ? Icons.login_rounded
                    : Icons.gpp_bad_rounded,
            color: DesignTokens.maroon,
            size: 20,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  event.eventType.replaceAll('_', ' '),
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    color: DesignTokens.ink,
                  ),
                ),
                Text(
                  [
                    if ((event.email ?? '').isNotEmpty) event.email!,
                    event.ipAddress,
                    event.createdAt,
                  ].join(' · '),
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 12.5,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AbuseFlag {
  final String kind;
  final String ipAddress;
  final int count;
  final int windowHours;
  final String reason;
  final String latestAt;
  final String eventType;
  final List<_RelatedUser> relatedUsers;

  const _AbuseFlag({
    required this.kind,
    required this.ipAddress,
    required this.count,
    required this.windowHours,
    required this.reason,
    required this.latestAt,
    required this.eventType,
    required this.relatedUsers,
  });

  factory _AbuseFlag.fromJson(Map<String, dynamic> json) {
    final users = json['related_users'] is List
        ? (json['related_users'] as List)
            .whereType<Map>()
            .map((item) =>
                _RelatedUser.fromJson(Map<String, dynamic>.from(item)))
            .toList()
        : <_RelatedUser>[];
    return _AbuseFlag(
      kind: (json['kind'] ?? '').toString(),
      ipAddress: (json['ip_address'] ?? '').toString(),
      count: int.tryParse((json['count'] ?? '0').toString()) ?? 0,
      windowHours: int.tryParse((json['window_hours'] ?? '0').toString()) ?? 0,
      reason: (json['reason'] ?? '').toString(),
      latestAt: (json['latest_at'] ?? '').toString(),
      eventType: (json['event_type'] ?? '').toString(),
      relatedUsers: users,
    );
  }
}

class _RelatedUser {
  final String id;
  final String email;
  final String fullName;
  final String role;
  final bool isActive;

  const _RelatedUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.role,
    required this.isActive,
  });

  factory _RelatedUser.fromJson(Map<String, dynamic> json) {
    return _RelatedUser(
      id: (json['id'] ?? '').toString(),
      email: (json['email'] ?? '').toString(),
      fullName: (json['full_name'] ?? '').toString(),
      role: (json['role'] ?? '').toString(),
      isActive: json['is_active'] != false,
    );
  }
}

class _AuthEventRow {
  final String id;
  final String eventType;
  final String? email;
  final String ipAddress;
  final String createdAt;

  const _AuthEventRow({
    required this.id,
    required this.eventType,
    required this.email,
    required this.ipAddress,
    required this.createdAt,
  });

  factory _AuthEventRow.fromJson(Map<String, dynamic> json) {
    return _AuthEventRow(
      id: (json['id'] ?? '').toString(),
      eventType: (json['event_type'] ?? '').toString(),
      email: (json['email'] ?? '').toString().trim().isEmpty
          ? null
          : (json['email'] ?? '').toString().trim(),
      ipAddress: (json['ip_address'] ?? '').toString(),
      createdAt: (json['created_at'] ?? '').toString(),
    );
  }
}

Future<List<_AbuseFlag>> _fetchFlags(BuildContext context) async {
  final result = await ApiClient.send(
    method: 'GET',
    url: '${AppConfig.resolvedApiBase}/auth/abuse/flags',
    headers: AuthScope.of(context).ticketHeaders(),
  );
  final data = _decodeObject(result.body);
  if (result.statusCode < 200 || result.statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not load abuse flags.'));
  }
  final items = data['items'] is List ? data['items'] as List : const [];
  return items
      .whereType<Map>()
      .map((item) => _AbuseFlag.fromJson(Map<String, dynamic>.from(item)))
      .toList();
}

Future<List<_AuthEventRow>> _fetchEvents(
  BuildContext context, {
  String? ip,
}) async {
  final params = <String, String>{
    'limit': '40',
    if (ip != null && ip.trim().isNotEmpty) 'ip': ip.trim(),
  };
  final query = '?${Uri(queryParameters: params).query}';
  final result = await ApiClient.send(
    method: 'GET',
    url: '${AppConfig.resolvedApiBase}/auth/abuse/events$query',
    headers: AuthScope.of(context).ticketHeaders(),
  );
  final data = _decodeObject(result.body);
  if (result.statusCode < 200 || result.statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not load auth events.'));
  }
  final items = data['items'] is List ? data['items'] as List : const [];
  return items
      .whereType<Map>()
      .map((item) => _AuthEventRow.fromJson(Map<String, dynamic>.from(item)))
      .toList();
}

Future<void> _setUserActive(
  BuildContext context, {
  required String userId,
  required bool isActive,
}) async {
  final result = await ApiClient.send(
    method: 'PATCH',
    url: '${AppConfig.resolvedApiBase}/auth/users/$userId/active',
    headers: {...AuthScope.of(context).ticketHeaders()},
    jsonBody: {'is_active': isActive},
  );
  final data = _decodeObject(result.body);
  if (result.statusCode < 200 || result.statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not update account status.'));
  }
}

Map<String, dynamic> _decodeObject(String body) {
  try {
    final parsed = jsonDecode(body);
    if (parsed is Map<String, dynamic>) return parsed;
    if (parsed is Map) return Map<String, dynamic>.from(parsed);
  } catch (_) {}
  return <String, dynamic>{'detail': body};
}

String _extractError(Map<String, dynamic> data, String fallback) {
  final detail = data['detail'];
  if (detail is String && detail.trim().isNotEmpty) return detail.trim();
  if (detail is List && detail.isNotEmpty) {
    return detail.map((e) => e.toString()).join(' ');
  }
  return fallback;
}

String _friendlyError(Object error) {
  return error
      .toString()
      .replaceFirst('Bad state: ', '')
      .replaceFirst('StateError: ', '');
}
