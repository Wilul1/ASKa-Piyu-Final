import 'package:flutter/material.dart';
import 'app_config.dart';
import 'app_route_observer.dart';
import 'auth/auth_state.dart';
import 'auth/session_expiry.dart';
import 'screens/student_home.dart';
import 'design_tokens.dart';
import 'navigation/soft_page_route.dart';
import 'services/kb_workspace_session.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppConfig.init();
  runApp(const MyApp());
}

class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  final AuthController _authController = AuthController();
  final KbWorkspaceSession _kbWorkspaceSession = KbWorkspaceSession();
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();

  @override
  void initState() {
    super.initState();
    SessionExpiry.bind(
      auth: _authController,
      navigatorKey: _navigatorKey,
    );
    _authController.addListener(_onAuthChanged);
    _authController.loadCurrentUser();
  }

  void _onAuthChanged() {
    if (!_authController.isAuthenticated) {
      _kbWorkspaceSession.clear();
    }
  }

  @override
  void dispose() {
    SessionExpiry.unbind();
    _authController.removeListener(_onAuthChanged);
    _authController.dispose();
    _kbWorkspaceSession.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AuthScope(
      controller: _authController,
      child: KbWorkspaceScope(
        session: _kbWorkspaceSession,
        child: MaterialApp(
          navigatorKey: _navigatorKey,
          navigatorObservers: [appRouteObserver],
          title: 'ASKa-Piyu',
          theme: ThemeData(
            primaryColor: DesignTokens.maroon,
            scaffoldBackgroundColor: DesignTokens.bgGrey,
            pageTransitionsTheme: softPageTransitionsTheme,
            colorScheme: ColorScheme.fromSeed(
              seedColor: DesignTokens.maroon,
              primary: DesignTokens.maroon,
              secondary: DesignTokens.gold,
              surface: Colors.white,
            ),
            appBarTheme: const AppBarTheme(
              backgroundColor: Colors.white,
              foregroundColor: DesignTokens.maroon,
              elevation: 0.5,
            ),
            textTheme: const TextTheme(
              headlineLarge: DesignTokens.h1,
              bodyMedium: DesignTokens.body,
            ),
          ),
          home: const StudentHomePage(),
        ),
      ),
    );
  }
}
