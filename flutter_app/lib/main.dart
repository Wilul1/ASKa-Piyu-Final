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
            useMaterial3: true,
            primaryColor: DesignTokens.maroon,
            scaffoldBackgroundColor: DesignTokens.pageBg,
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
              elevation: 0,
              scrolledUnderElevation: 0.5,
              centerTitle: false,
            ),
            elevatedButtonTheme: ElevatedButtonThemeData(
              style: DesignTokens.primaryButtonStyle(),
            ),
            outlinedButtonTheme: OutlinedButtonThemeData(
              style: DesignTokens.secondaryButtonStyle(),
            ),
            filledButtonTheme: FilledButtonThemeData(
              style: DesignTokens.primaryButtonStyle(),
            ),
            inputDecorationTheme: DesignTokens.inputDecorationTheme(),
            chipTheme: ChipThemeData(
              backgroundColor: DesignTokens.maroonWash,
              selectedColor: DesignTokens.maroonWash,
              disabledColor: DesignTokens.bgGrey,
              labelStyle: const TextStyle(
                color: DesignTokens.maroon,
                fontWeight: FontWeight.w600,
                fontSize: 12,
              ),
              side: BorderSide.none,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(999),
              ),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 0),
            ),
            cardTheme: CardThemeData(
              color: DesignTokens.cardBg,
              elevation: 0,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(DesignTokens.radius),
                side: const BorderSide(color: DesignTokens.border),
              ),
            ),
            dividerTheme: const DividerThemeData(
              color: DesignTokens.border,
              thickness: 1,
              space: 1,
            ),
            textTheme: const TextTheme(
              headlineLarge: DesignTokens.h1,
              headlineMedium: DesignTokens.h2,
              titleMedium: DesignTokens.subtitle,
              bodyMedium: DesignTokens.body,
            ),
          ),
          home: const StudentHomePage(),
        ),
      ),
    );
  }
}
