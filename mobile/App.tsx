import AsyncStorage from '@react-native-async-storage/async-storage';
import { fetch as expoFetch } from 'expo/fetch';
import { File } from 'expo-file-system';
import * as ImagePicker from 'expo-image-picker';
import { StatusBar } from 'expo-status-bar';
import { useShareIntent } from 'expo-share-intent';
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {
  ActivityIndicator,
  Image,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

const API_URL_STORAGE_KEY = 'factshield-api-url';

type SelectedImage = {
  uri: string;
  name: string;
};

type VerificationResult = {
  verdict: string;
  confidence_score?: number;
  explanation?: string;
  primary_claim?: string;
  sources?: unknown;
  ocr_result?: unknown;
  image_origin?: unknown;
  web_search?: unknown;
  fact_check_lookup?: unknown;
  disclaimer?: string;
};

type ImageOriginResult = {
  status: string;
  verdict: string;
  explanation: string;
  disclaimer?: string;
  message?: string;
  model?: string;
};

type Source = {
  url: string;
  title?: string;
  source_type?: string;
  publisher?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isSource(value: unknown): value is Source {
  return isRecord(value) && typeof value.url === 'string';
}

function isVerificationResult(value: unknown): value is VerificationResult {
  return isRecord(value) && typeof value.verdict === 'string';
}

function isImageOriginResult(value: unknown): value is ImageOriginResult {
  return (
    isRecord(value) &&
    typeof value.status === 'string' &&
    typeof value.verdict === 'string' &&
    typeof value.explanation === 'string' &&
    (value.disclaimer === undefined || typeof value.disclaimer === 'string') &&
    (value.message === undefined || typeof value.message === 'string') &&
    (value.model === undefined || typeof value.model === 'string')
  );
}

function normalizeApiUrl(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error('Enter the address of your FactShield server.');
  }

  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    throw new Error('Enter a complete server address, such as https://example.com.');
  }

  if (!['http:', 'https:'].includes(url.protocol) || !url.host) {
    throw new Error('The server address must start with http:// or https://.');
  }
  if (url.username || url.password) {
    throw new Error('Do not include credentials in the server address.');
  }

  return url.toString().replace(/\/+$/, '');
}

function getVerdictColor(verdict: string): string {
  switch (verdict) {
    case 'Likely False':
      return '#ff6b73';
    case 'Likely True':
      return '#46d7a2';
    case 'Disputed':
      return '#ffc36b';
    default:
      return '#aab4ca';
  }
}

export default function App() {
  const { hasShareIntent, isReady, resetShareIntent, shareIntent, error: shareError } =
    useShareIntent({ scheme: 'factshield' });
  const [apiUrl, setApiUrl] = useState('');
  const [apiReady, setApiReady] = useState(false);
  const [claim, setClaim] = useState('');
  const [image, setImage] = useState<SelectedImage | null>(null);
  const [result, setResult] = useState<VerificationResult | null>(null);
  const [requestError, setRequestError] = useState('');
  const [settingsError, setSettingsError] = useState('');
  const [isVerifying, setIsVerifying] = useState(false);
  const processedShareRef = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    AsyncStorage.getItem(API_URL_STORAGE_KEY)
      .then((savedUrl) => {
        if (active) {
          setApiUrl(savedUrl ?? process.env.EXPO_PUBLIC_API_URL ?? '');
          setApiReady(true);
        }
      })
      .catch(() => {
        if (active) {
          setSettingsError('Could not load the saved server address. You can enter it again below.');
          setApiReady(true);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  const verifyClaim = useCallback(
    async (text: string, selectedImage: SelectedImage | null) => {
      setRequestError('');
      setResult(null);

      if (!apiUrl.trim()) {
        setRequestError('Add your FactShield server address below before verifying.');
        return;
      }
      if (!text.trim() && !selectedImage) {
        setRequestError('Enter claim text or choose an image to verify.');
        return;
      }

      setIsVerifying(true);
      try {
        const formData = new FormData();
        if (text.trim()) {
          formData.append('text', text.trim());
        }
        if (selectedImage) {
          formData.append('image', new File(selectedImage.uri));
        }

        const response = await expoFetch(`${apiUrl.replace(/\/+$/, '')}/api/verify`, {
          method: 'POST',
          body: formData,
        });
        const payload: unknown = await response.json();

        if (!isRecord(payload)) {
          throw new Error('The server returned an unreadable response.');
        }
        if (!response.ok) {
          throw new Error(
            typeof payload.error === 'string'
              ? payload.error
              : `Verification failed (HTTP ${response.status}).`,
          );
        }
        if (!isVerificationResult(payload)) {
          throw new Error('The server response did not contain a verification verdict.');
        }

        setResult(payload);
      } catch (error) {
        setRequestError(
          error instanceof Error ? error.message : 'Could not contact the FactShield server.',
        );
      } finally {
        setIsVerifying(false);
      }
    },
    [apiUrl],
  );

  useEffect(() => {
    if (!hasShareIntent) {
      processedShareRef.current = null;
      return;
    }
    if (!isReady || !apiReady) {
      return;
    }

    const sharedImage = shareIntent.files?.find((file) => file.mimeType?.startsWith('image/'));
    const sharedText = shareIntent.text?.trim() ?? '';
    const shareKey = `${sharedText}|${sharedImage?.path ?? ''}`;
    if (processedShareRef.current === shareKey) {
      return;
    }
    processedShareRef.current = shareKey;

    if (shareIntent.files?.length && !sharedImage) {
      return;
    }

    const selectedImage = sharedImage
      ? {
          uri: sharedImage.path,
          name: sharedImage.fileName || 'shared-image',
        }
      : null;

    let completed = false;
    const timer = setTimeout(() => {
      completed = true;
      setClaim(sharedText);
      setImage(selectedImage);
      setResult(null);
      setRequestError('');

      if (apiUrl.trim()) {
        void verifyClaim(sharedText, selectedImage);
      } else {
        setRequestError('Shared content is ready. Add your server address below, then tap Verify.');
      }

      resetShareIntent();
    }, 0);

    return () => {
      clearTimeout(timer);
      if (!completed && processedShareRef.current === shareKey) {
        processedShareRef.current = null;
      }
    };
  }, [
    apiReady,
    apiUrl,
    hasShareIntent,
    isReady,
    resetShareIntent,
    shareIntent,
    verifyClaim,
  ]);

  const saveApiUrl = async () => {
    setSettingsError('');
    try {
      const normalizedUrl = normalizeApiUrl(apiUrl);
      await AsyncStorage.setItem(API_URL_STORAGE_KEY, normalizedUrl);
      setApiUrl(normalizedUrl);
    } catch (error) {
      setSettingsError(
        error instanceof Error ? error.message : 'Could not save the server address.',
      );
    }
  };

  const chooseImage = async () => {
    setRequestError('');
    try {
      const selection = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        quality: 0.9,
      });
      if (!selection.canceled) {
        const asset = selection.assets[0];
        setImage({
          uri: asset.uri,
          name: asset.fileName ?? 'selected-image',
        });
        setResult(null);
      }
    } catch (error) {
      setRequestError(
        error instanceof Error ? error.message : 'Could not open the photo library.',
      );
    }
  };

  const sources = Array.isArray(result?.sources) ? result.sources.filter(isSource) : [];
  const ocrResult = isRecord(result?.ocr_result) ? result.ocr_result : null;
  const imageOrigin = isImageOriginResult(result?.image_origin) ? result.image_origin : null;
  const lookupResult = isRecord(result?.fact_check_lookup) ? result.fact_check_lookup : null;
  const webSearchResult = isRecord(result?.web_search) ? result.web_search : null;
  const resultNotes = [
    ocrResult && typeof ocrResult.error === 'string' ? ocrResult.error : '',
    lookupResult && typeof lookupResult.message === 'string' ? lookupResult.message : '',
    webSearchResult && typeof webSearchResult.message === 'string' ? webSearchResult.message : '',
  ].filter(Boolean);
  const unsupportedSharedFile =
    hasShareIntent &&
    Boolean(shareIntent.files?.length) &&
    !shareIntent.files?.some((file) => file.mimeType?.startsWith('image/'));

  return (
    <View style={styles.screen}>
      <StatusBar style="light" />
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.header}>
          <View style={styles.brandMark}>
            <Text style={styles.brandMarkText}>F</Text>
          </View>
          <View>
            <Text style={styles.eyebrow}>FACTSHIELD</Text>
            <Text style={styles.title}>Check before you share.</Text>
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>What would you like to verify?</Text>
          <Text style={styles.helper}>
            Paste a claim or add an image for an experimental AI-origin estimate. You can also
            share text or a picture to FactShield from another app.
          </Text>

          <TextInput
            accessibilityLabel="Claim text"
            multiline
            onChangeText={setClaim}
            placeholder="Paste a message, headline, or claim..."
            placeholderTextColor="#77829a"
            style={styles.claimInput}
            textAlignVertical="top"
            value={claim}
          />

          {image ? (
            <View style={styles.imageRow}>
              <Image source={{ uri: image.uri }} style={styles.thumbnail} />
              <Text numberOfLines={1} style={styles.imageName}>
                {image.name}
              </Text>
              <Pressable
                accessibilityLabel="Remove image"
                onPress={() => setImage(null)}
                style={styles.removeImage}
              >
                <Text style={styles.removeImageText}>Remove</Text>
              </Pressable>
            </View>
          ) : null}

          <View style={styles.actions}>
            <Pressable onPress={chooseImage} style={styles.secondaryButton}>
              <Text style={styles.secondaryButtonText}>Choose image</Text>
            </Pressable>
            <Pressable
              disabled={isVerifying}
              onPress={() => void verifyClaim(claim, image)}
              style={[styles.primaryButton, isVerifying && styles.disabledButton]}
            >
              {isVerifying ? (
                <ActivityIndicator color="#08101e" />
              ) : (
                <Text style={styles.primaryButtonText}>Verify</Text>
              )}
            </Pressable>
          </View>

          {unsupportedSharedFile ? (
            <View>
              <Text style={styles.errorText}>
                FactShield accepts shared text or images, not this file type.
              </Text>
              <Pressable onPress={() => resetShareIntent()} style={styles.removeImage}>
                <Text style={styles.removeImageText}>Dismiss</Text>
              </Pressable>
            </View>
          ) : requestError ? (
            <Text style={styles.errorText}>{requestError}</Text>
          ) : null}
          {shareError ? <Text style={styles.errorText}>{shareError}</Text> : null}
        </View>

        {result ? (
          <View style={styles.resultCard}>
            <Text style={styles.eyebrow}>VERIFICATION RESULT</Text>
            <Text style={[styles.verdict, { color: getVerdictColor(result.verdict) }]}>
              {result.verdict}
            </Text>
            {typeof result.confidence_score === 'number' ? (
              <Text style={styles.confidence}>{result.confidence_score}% confidence estimate</Text>
            ) : null}
            {result.primary_claim ? (
              <Text style={styles.resultClaim}>{result.primary_claim}</Text>
            ) : null}
            <Text style={styles.explanation}>
              {result.explanation || 'No explanation was returned.'}
            </Text>

            {imageOrigin ? (
              <View style={styles.imageOriginCard}>
                <Text style={styles.eyebrow}>IMAGE ORIGIN — EXPERIMENTAL</Text>
                <Text style={styles.imageOriginVerdict}>{imageOrigin.verdict}</Text>
                <Text style={styles.explanation}>{imageOrigin.explanation}</Text>
                {imageOrigin.message && imageOrigin.message !== imageOrigin.explanation ? (
                  <Text style={styles.noteText}>{imageOrigin.message}</Text>
                ) : null}
                <Text style={styles.disclaimer}>
                  {imageOrigin.disclaimer ||
                    "Visual AI-image detection is uncertain and cannot prove an image's origin."}
                </Text>
              </View>
            ) : null}

            {resultNotes.map((note, index) => (
              <Text key={`${index}-${note}`} style={styles.noteText}>
                {note}
              </Text>
            ))}

            <Text style={styles.sourcesTitle}>Sources</Text>
            {sources.length ? (
              sources.map((source) => (
                <Pressable
                  accessibilityRole="link"
                  key={source.url}
                  onPress={() => {
                    if (/^https?:\/\//i.test(source.url)) {
                      void Linking.openURL(source.url);
                    }
                  }}
                  style={styles.sourceLink}
                >
                  <Text style={styles.sourceLinkText}>
                    {source.source_type || source.publisher || 'Source'}:{' '}
                    {source.title || source.url}
                  </Text>
                </Pressable>
              ))
            ) : (
              <Text style={styles.helper}>No citable source was returned.</Text>
            )}

            {result.disclaimer ? <Text style={styles.disclaimer}>{result.disclaimer}</Text> : null}
          </View>
        ) : null}

        <View style={styles.settingsCard}>
          <Text style={styles.sectionTitle}>Connect your server</Text>
          <Text style={styles.helper}>
            Use an HTTPS address reachable from this phone. A 127.0.0.1 address points to the
            phone, not your computer.
          </Text>
          <TextInput
            accessibilityLabel="FactShield server address"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            onChangeText={setApiUrl}
            placeholder="https://your-factshield-server.example"
            placeholderTextColor="#77829a"
            style={styles.urlInput}
            value={apiUrl}
          />
          <Pressable onPress={() => void saveApiUrl()} style={styles.saveButton}>
            <Text style={styles.secondaryButtonText}>Save server address</Text>
          </Pressable>
          {settingsError ? <Text style={styles.errorText}>{settingsError}</Text> : null}
        </View>

        <Text style={styles.footer}>
          FactShield is an automated aid, not a guarantee of truth. Check important claims
          against reliable sources.
        </Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: '#080d19',
  },
  content: {
    width: '100%',
    maxWidth: 680,
    alignSelf: 'center',
    paddingHorizontal: 20,
    paddingTop: 64,
    paddingBottom: 40,
    gap: 18,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    marginBottom: 4,
  },
  brandMark: {
    width: 48,
    height: 48,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#8cf0cb',
  },
  brandMarkText: {
    color: '#08101e',
    fontSize: 28,
    fontWeight: '900',
  },
  eyebrow: {
    color: '#8cf0cb',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1.8,
  },
  title: {
    color: '#f4f6fb',
    fontSize: 23,
    fontWeight: '800',
    marginTop: 3,
  },
  card: {
    backgroundColor: '#121a2b',
    borderColor: '#263249',
    borderWidth: 1,
    borderRadius: 22,
    padding: 18,
  },
  sectionTitle: {
    color: '#f4f6fb',
    fontSize: 18,
    fontWeight: '700',
  },
  helper: {
    color: '#aab4ca',
    fontSize: 13,
    lineHeight: 19,
    marginTop: 7,
  },
  claimInput: {
    minHeight: 138,
    marginTop: 18,
    padding: 14,
    borderWidth: 1,
    borderColor: '#33415a',
    borderRadius: 14,
    backgroundColor: '#0b1220',
    color: '#f4f6fb',
    fontSize: 15,
    lineHeight: 22,
  },
  imageRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginTop: 12,
    padding: 8,
    borderRadius: 12,
    backgroundColor: '#0b1220',
  },
  thumbnail: {
    width: 44,
    height: 44,
    borderRadius: 8,
    backgroundColor: '#263249',
  },
  imageName: {
    color: '#dce3f2',
    flex: 1,
    fontSize: 13,
  },
  removeImage: {
    padding: 8,
  },
  removeImageText: {
    color: '#ff9298',
    fontSize: 12,
    fontWeight: '700',
  },
  actions: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 14,
  },
  secondaryButton: {
    flex: 1,
    minHeight: 48,
    alignItems: 'center',
    justifyContent: 'center',
    borderColor: '#52617b',
    borderWidth: 1,
    borderRadius: 12,
  },
  secondaryButtonText: {
    color: '#e5eaf4',
    fontSize: 14,
    fontWeight: '700',
  },
  primaryButton: {
    flex: 1,
    minHeight: 48,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    backgroundColor: '#8cf0cb',
  },
  primaryButtonText: {
    color: '#08101e',
    fontSize: 15,
    fontWeight: '800',
  },
  disabledButton: {
    opacity: 0.65,
  },
  errorText: {
    color: '#ff9298',
    fontSize: 13,
    lineHeight: 19,
    marginTop: 12,
  },
  resultCard: {
    backgroundColor: '#121a2b',
    borderColor: '#263249',
    borderWidth: 1,
    borderRadius: 22,
    padding: 18,
  },
  verdict: {
    fontSize: 27,
    fontWeight: '800',
    marginTop: 9,
  },
  confidence: {
    color: '#aab4ca',
    fontSize: 13,
    marginTop: 3,
  },
  resultClaim: {
    color: '#dce3f2',
    fontSize: 15,
    fontWeight: '700',
    lineHeight: 22,
    marginTop: 18,
  },
  explanation: {
    color: '#c4ccdc',
    fontSize: 14,
    lineHeight: 22,
    marginTop: 10,
  },
  imageOriginCard: {
    marginTop: 16,
    padding: 14,
    borderWidth: 1,
    borderColor: '#52617b',
    borderRadius: 14,
    backgroundColor: '#0b1220',
  },
  imageOriginVerdict: {
    color: '#ffc36b',
    fontSize: 18,
    fontWeight: '800',
    marginTop: 8,
  },
  noteText: {
    color: '#aab4ca',
    fontSize: 12,
    lineHeight: 18,
    marginTop: 10,
  },
  sourcesTitle: {
    color: '#f4f6fb',
    fontSize: 15,
    fontWeight: '700',
    marginTop: 20,
    marginBottom: 8,
  },
  sourceLink: {
    paddingVertical: 6,
  },
  sourceLinkText: {
    color: '#8cf0cb',
    fontSize: 13,
    lineHeight: 19,
  },
  disclaimer: {
    color: '#77829a',
    fontSize: 11,
    lineHeight: 17,
    marginTop: 14,
  },
  settingsCard: {
    backgroundColor: '#121a2b',
    borderColor: '#263249',
    borderWidth: 1,
    borderRadius: 22,
    padding: 18,
  },
  urlInput: {
    minHeight: 46,
    marginTop: 14,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: '#33415a',
    borderRadius: 12,
    backgroundColor: '#0b1220',
    color: '#f4f6fb',
    fontSize: 14,
  },
  saveButton: {
    alignSelf: 'flex-start',
    minHeight: 42,
    justifyContent: 'center',
    paddingHorizontal: 14,
    marginTop: 10,
    borderWidth: 1,
    borderColor: '#52617b',
    borderRadius: 12,
  },
  footer: {
    color: '#77829a',
    fontSize: 11,
    lineHeight: 17,
    textAlign: 'center',
    paddingHorizontal: 10,
  },
});
