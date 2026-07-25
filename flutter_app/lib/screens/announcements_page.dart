import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../services/api_client.dart';
import '../widgets/public_site_header.dart';
import '../widgets/sidebar.dart';

class AnnouncementsPage extends StatefulWidget {
  const AnnouncementsPage({super.key});

  @override
  State<AnnouncementsPage> createState() => _AnnouncementsPageState();
}

class _AnnouncementsPageState extends State<AnnouncementsPage> {
  bool _loading = true;
  String? _error;
  List<_Announcement> _items = const [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final auth = AuthScope.of(context);
    final includeUnpublished = auth.role == 'admin';
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url:
            '${AppConfig.resolvedApiBase}/announcements${includeUnpublished ? '?include_unpublished=true' : ''}',
        headers: auth.ticketHeaders(),
      );
      if (!mounted) return;
      if (!result.ok) {
        setState(() {
          _error = ApiClient.extractError(
            result.jsonObject,
            fallback: 'Could not load announcements.',
          );
          _loading = false;
        });
        return;
      }
      final raw = result.jsonObject['items'];
      final items = <_Announcement>[];
      if (raw is List) {
        for (final row in raw) {
          if (row is Map) {
            items.add(_Announcement.fromJson(
              row.map((k, v) => MapEntry(k.toString(), v)),
            ));
          }
        }
      }
      setState(() {
        _items = items;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not reach the API for announcements.';
        _loading = false;
      });
    }
  }

  Future<void> _createAnnouncement() async {
    final titleCtrl = TextEditingController();
    final bodyCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('New announcement'),
        content: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: titleCtrl,
                decoration: const InputDecoration(labelText: 'Title'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: bodyCtrl,
                maxLines: 5,
                decoration: const InputDecoration(labelText: 'Body'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Publish'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final auth = AuthScope.of(context);
    final result = await ApiClient.send(
      method: 'POST',
      url: '${AppConfig.resolvedApiBase}/announcements',
      headers: {
        ...auth.ticketHeaders(),
        'Content-Type': 'application/json',
      },
      jsonBody: {
        'title': titleCtrl.text.trim(),
        'body': bodyCtrl.text.trim(),
        'published': true,
      },
    );
    if (!mounted) return;
    if (!result.ok) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            ApiClient.extractError(
              result.jsonObject,
              fallback: 'Could not publish announcement.',
            ),
          ),
        ),
      );
      return;
    }
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final isAdmin = AuthScope.of(context).role == 'admin';
    return Scaffold(
      backgroundColor: Colors.white,
      body: Row(
        children: [
          const AppSidebar(current: StudentNavItem.announcements),
          Expanded(
            child: Column(
              children: [
                const PublicSiteHeader(),
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: _load,
                    child: ListView(
                      padding: const EdgeInsets.all(24),
                      children: [
                        Row(
                          children: [
                            const Expanded(
                              child: Text(
                                'Announcements',
                                style: TextStyle(
                                  fontSize: 24,
                                  fontWeight: FontWeight.w800,
                                  color: DesignTokens.maroon,
                                ),
                              ),
                            ),
                            if (isAdmin)
                              FilledButton.icon(
                                onPressed: _createAnnouncement,
                                icon: const Icon(Icons.add),
                                label: const Text('New'),
                              ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        if (_loading)
                          const Center(child: CircularProgressIndicator())
                        else if (_error != null)
                          Text(_error!, style: const TextStyle(color: Colors.red))
                        else if (_items.isEmpty)
                          const Text(
                            'No announcements yet.',
                            style: TextStyle(color: DesignTokens.muted),
                          )
                        else
                          ..._items.map(
                            (item) => Card(
                              margin: const EdgeInsets.only(bottom: 12),
                              child: Padding(
                                padding: const EdgeInsets.all(16),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      children: [
                                        Expanded(
                                          child: Text(
                                            item.title,
                                            style: const TextStyle(
                                              fontSize: 18,
                                              fontWeight: FontWeight.w700,
                                            ),
                                          ),
                                        ),
                                        if (!item.published)
                                          const Chip(label: Text('Draft')),
                                      ],
                                    ),
                                    const SizedBox(height: 8),
                                    Text(
                                      item.body,
                                      style: const TextStyle(height: 1.45),
                                    ),
                                    const SizedBox(height: 8),
                                    Text(
                                      item.createdAt,
                                      style: const TextStyle(
                                        fontSize: 12,
                                        color: DesignTokens.muted,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                      ],
                    ),
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

class _Announcement {
  final String id;
  final String title;
  final String body;
  final bool published;
  final String createdAt;

  const _Announcement({
    required this.id,
    required this.title,
    required this.body,
    required this.published,
    required this.createdAt,
  });

  factory _Announcement.fromJson(Map<String, dynamic> json) {
    return _Announcement(
      id: json['id']?.toString() ?? '',
      title: json['title']?.toString() ?? '',
      body: json['body']?.toString() ?? '',
      published: json['published'] == true,
      createdAt: json['created_at']?.toString() ?? '',
    );
  }
}
