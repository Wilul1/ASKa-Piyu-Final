import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

android {
    namespace = "ph.edu.lspu.aska_piyu"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        applicationId = "ph.edu.lspu.aska_piyu"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            create("release") {
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
                storeFile = keystoreProperties["storeFile"]?.let { file(it as String) }
                storePassword = keystoreProperties["storePassword"] as String
            }
        }
    }

    buildTypes {
        release {
            // Never silently ship with the debug keystore.
            // Campus MDM / Play Store: create a keystore + android/key.properties
            // (see key.properties.example). Local smoke only: ASKA_ALLOW_DEBUG_RELEASE_SIGNING=true
            signingConfig = when {
                keystorePropertiesFile.exists() -> signingConfigs.getByName("release")
                System.getenv("ASKA_ALLOW_DEBUG_RELEASE_SIGNING") == "true" ||
                    (project.findProperty("allowDebugReleaseSigning") as String?) == "true" -> {
                    logger.warn(
                        "Signing RELEASE with the DEBUG keystore " +
                            "(ASKA_ALLOW_DEBUG_RELEASE_SIGNING). Not for Play Store / MDM.",
                    )
                    signingConfigs.getByName("debug")
                }
                else -> throw GradleException(
                    "Release builds require flutter_app/android/key.properties. " +
                        "Copy key.properties.example, create a keystore, then rebuild. " +
                        "For local-only testing set ASKA_ALLOW_DEBUG_RELEASE_SIGNING=true.",
                )
            }
        }
    }
}

flutter {
    source = "../.."
}
