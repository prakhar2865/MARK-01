import { useEffect, useMemo, useRef, useState } from "react";

import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  FileSearch,
  FileText,
  HelpCircle,
  LayoutDashboard,
  Loader2,
  RotateCcw,
  ScanLine,
  ScanSearch,
  Settings,
  ShieldAlert,
  ShieldCheck,
  UploadCloud,
  X,
  Image as ImageIcon,
  Search,
  Clock3,
  Database,
  Eye,
  Sun,
  Moon,
  Camera,
  Shield,
  LogIn,
  LogOut,
  UserX,
  Video,
  VideoOff,
} from "lucide-react";

import "./App.css";


/* =========================================================
   HELPER FUNCTIONS
========================================================= */

function cleanText(value) {
  if (!value) return "";

  return String(value)
    .replace(/\s+/g, " ")
    .trim();
}


function getFirstAvailable(...values) {
  for (const value of values) {
    if (
      value !== undefined &&
      value !== null &&
      String(value).trim() !== ""
    ) {
      return value;
    }
  }

  return "";
}


function getNestedValue(object, paths) {
  for (const path of paths) {
    const parts = path.split(".");
    let current = object;

    for (const part of parts) {
      if (
        current === null ||
        current === undefined ||
        typeof current !== "object"
      ) {
        current = undefined;
        break;
      }

      current = current[part];
    }

    if (
      current !== undefined &&
      current !== null &&
      String(current).trim() !== ""
    ) {
      return current;
    }
  }

  return "";
}


/* =========================================================
   OCR FALLBACK EXTRACTION
========================================================= */

function extractIdentityFromOCR(text) {
  const result = {
    name: "",
    dob: "",
    idNumber: "",
    validity: "",
  };

  if (!text) {
    return result;
  }

  const normalized = text
    .replace(/\r/g, "\n")
    .replace(/[ \t]+/g, " ");


  /* NAME */

  const namePatterns = [
    /(?:Name|Full Name)\s*[:\-]?\s*([A-Za-z][A-Za-z .'-]{2,40})/i,
    /Student\s+Name\s*[:\-]?\s*([A-Za-z][A-Za-z .'-]{2,40})/i,
  ];

  for (const pattern of namePatterns) {
    const match = normalized.match(pattern);

    if (match) {
      result.name = cleanText(match[1]);
      break;
    }
  }


  /* DOB */

  const dobPatterns = [
    /(?:Date\s+of\s+Birth|DOB|Birth)\s*[:\-]?\s*(\d{1,2}\s*[A-Za-z]{3,9}[,\s-]+\d{4})/i,
    /(\d{1,2}\s+[A-Za-z]{3,9}[,\s]+\d{4})/i,
    /(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})/,
  ];

  for (const pattern of dobPatterns) {
    const match = normalized.match(pattern);

    if (match) {
      result.dob = cleanText(match[1]);
      break;
    }
  }


  /* ID */

  const idPatterns = [
    /(?:ID|ID\s*No|ID\s*Number|Document\s*No|Passport\s*No|Number)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-]{4,20})/i,
    /\b\d{2}[A-Z]{2,5}\d{3,8}\b/i,
  ];

  for (const pattern of idPatterns) {
    const match = normalized.match(pattern);

    if (match) {
      result.idNumber = cleanText(match[1]);
      break;
    }
  }


  /* VALIDITY */

  const validityPatterns = [
    /(?:Validity|Valid\s*Until|Expiry|Expires)\s*[:\-]?\s*(\d{4}\s*[-–]\s*\d{4})/i,
    /(?:Validity|Valid\s*Until|Expiry|Expires)\s*[:\-]?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})/i,
    /\b(20\d{2}\s*[-–]\s*20\d{2})\b/,
  ];

  for (const pattern of validityPatterns) {
    const match = normalized.match(pattern);

    if (match) {
      result.validity = cleanText(match[1]);
      break;
    }
  }

  return result;
}


/* =========================================================
   HISTORY STORAGE
========================================================= */

const API_BASE_URL = "http://127.0.0.1:8000";

const AUTH_TOKEN_KEY = "veriguard_auth_token";
const AUTH_OFFICER_KEY = "veriguard_officer";


const DEMO_HISTORY = [
  {
    caseId: "VG-1042",
    documentType: "Passport",
    status: "VERIFIED",
    riskScore: 8,
    confidence: "HIGH",
    time: "10:42",
    date: "Today",
  },
  {
    caseId: "VG-1041",
    documentType: "Visa",
    status: "REVIEW",
    riskScore: 43,
    confidence: "MEDIUM",
    time: "10:37",
    date: "Today",
  },
  {
    caseId: "VG-1040",
    documentType: "Identity Card",
    status: "VERIFIED",
    riskScore: 5,
    confidence: "HIGH",
    time: "10:31",
    date: "Today",
  },
  {
    caseId: "VG-1039",
    documentType: "Driving License",
    status: "HIGH RISK",
    riskScore: 78,
    confidence: "MEDIUM",
    time: "10:24",
    date: "Today",
  },
];


function normalizeHistoryRecord(record, index = 0) {
  const riskScore = Number(
    record?.risk_assessment?.score ??
    record?.tampering_analysis?.score ??
    record?.riskScore ??
    0
  );

  const screenedAt =
    record?.screened_at ||
    record?.created_at ||
    record?.timestamp ||
    null;

  const dateObject = screenedAt ? new Date(screenedAt) : null;

  return {
    caseId:
      record?.case_id ||
      record?.caseId ||
      `VG-${String(index + 1).padStart(4, "0")}`,

    documentType:
      record?.document_type ||
      record?.documentType ||
      "Document",

    status:
      record?.screening_status ||
      record?.status ||
      getRiskStatus(riskScore),

    riskScore,

    confidence:
      record?.risk_assessment?.confidence ||
      record?.tampering_analysis?.confidence ||
      record?.confidence ||
      "LOW",

    time:
      dateObject && !Number.isNaN(dateObject.getTime())
        ? dateObject.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })
        : record?.time || "--",

    date:
      dateObject && !Number.isNaN(dateObject.getTime())
        ? dateObject.toLocaleDateString()
        : record?.date || "--",

    filename: record?.filename || "",
    name: record?.name || record?.extracted_fields?.name || "",
    dob: record?.date_of_birth || record?.dob || "",
    idNumber:
      record?.id_number ||
      record?.document_number ||
      record?.passport_number ||
      "",

    validity:
      record?.validity ||
      record?.expiry ||
      "",

    referenceVerification: record?.reference_verification || null,
    validation: record?.validation || null,
  };
}

function getHistoryFromResponse(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.history)) return data.history;
  if (Array.isArray(data?.cases)) return data.cases;
  if (Array.isArray(data?.data)) return data.data;
  return [];
}


/* =========================================================
   STATUS HELPERS
========================================================= */

function getRiskStatus(score) {
  if (score >= 80) return "CRITICAL RISK";
  if (score >= 60) return "HIGH RISK";
  if (score >= 35) return "MEDIUM RISK";
  if (score >= 20) return "LOW RISK · REVIEW";
  return "LOW RISK";
}


function getRiskClass(score) {
  if (score >= 60) {
    return "high";
  }

  if (score >= 35) {
    return "review";
  }

  return "verified";
}


function formatTime() {
  return new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}


/* =========================================================
   AUTHENTICATION SCREEN
========================================================= */

function LoginScreen({ onLogin, theme, onToggleTheme }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");

    if (!username.trim() || !password) {
      setError("Please enter your officer ID / username and password.");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data?.detail || "Invalid officer credentials.");
      }

      if (!data?.token) {
        throw new Error("Authentication server returned no session token.");
      }

      localStorage.setItem(AUTH_TOKEN_KEY, data.token);
      if (data.officer) {
        localStorage.setItem(AUTH_OFFICER_KEY, JSON.stringify(data.officer));
      }

      onLogin(data.officer || { username: username.trim() });
    } catch (err) {
      console.error("Login failed:", err);
      setError(err?.message || "Unable to sign in. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-screen">
      <button
        type="button"
        className="login-theme-toggle theme-toggle"
        onClick={onToggleTheme}
        aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
        title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
      >
        {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
      </button>

      <div className="login-shell">
        <div className="login-brand">
          <div className="login-brand-icon"><ShieldCheck size={22} /></div>
          <div>
            <div className="login-brand-title">VERIGUARD</div>
            <div className="login-brand-subtitle">IDENTITY SECURITY OPERATIONS</div>
          </div>
        </div>

        <div className="login-card">
          <div className="login-card-header">
            <span className="login-eyebrow">AUTHORIZED ACCESS</span>
            <h2>Officer Sign In</h2>
            <p>Enter the credentials issued for your screening desk.</p>
          </div>

          <form onSubmit={handleSubmit} className="login-form">
            <label className="login-label">OFFICER ID / USERNAME</label>
            <input
              className="login-input"
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              placeholder="Enter officer ID"
              disabled={loading}
            />

            <label className="login-label">PASSWORD</label>
            <div className="login-password-wrap">
              <input
                className="login-input"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                placeholder="Enter password"
                disabled={loading}
              />
              <button
                type="button"
                className="login-password-toggle"
                onClick={() => setShowPassword((value) => !value)}
                disabled={loading}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                <Eye size={16} />
              </button>
            </div>

            {error && <div className="login-error">{error}</div>}

            <button type="submit" className="login-submit" disabled={loading}>
              {loading ? "Authenticating..." : "Sign in securely"}
            </button>
          </form>

          <div className="login-footer">
            <span className="login-status-dot" />
            VERIGUARD • Authorized Screening Console
          </div>
        </div>
      </div>
    </div>
  );
}

/* =========================================================
   APP
========================================================= */

function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [authChecking, setAuthChecking] = useState(true);
  const [officer, setOfficer] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("veriguard_theme") || "dark");

  const toggleTheme = () => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  };

  useEffect(() => {
    document.body.classList.toggle("veriguard-light", theme === "light");
    localStorage.setItem("veriguard_theme", theme);
    return () => document.body.classList.remove("veriguard-light");
  }, [theme]);

  const authToken = () => localStorage.getItem(AUTH_TOKEN_KEY);

  const authFetch = async (url, options = {}) => {
    const token = authToken();
    const headers = new Headers(options.headers || {});
    if (token) headers.set("Authorization", `Bearer ${token}`);

    const response = await fetch(url, { ...options, headers });

    if (response.status === 401) {
      localStorage.removeItem(AUTH_TOKEN_KEY);
      localStorage.removeItem(AUTH_OFFICER_KEY);
      setAuthenticated(false);
      setOfficer(null);
    }

    return response;
  };

  const handleLogin = (loggedOfficer) => {
    setOfficer(loggedOfficer);
    setAuthenticated(true);
  };

  const handleLogout = async () => {
    try {
      const token = authToken();
      if (token) {
        await fetch(`${API_BASE_URL}/auth/logout`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      }
    } catch (error) {
      console.error("Logout failed:", error);
    } finally {
      localStorage.removeItem(AUTH_TOKEN_KEY);
      localStorage.removeItem(AUTH_OFFICER_KEY);
      setOfficer(null);
      setAuthenticated(false);
      setCurrentPage("dashboard");
    }
  };

  useEffect(() => {
    const token = authToken();

    if (!token) {
      setAuthChecking(false);
      return;
    }

    fetch(`${API_BASE_URL}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Session invalid");
        return response.json();
      })
      .then((data) => {
        setOfficer(data.officer);
        setAuthenticated(true);
      })
      .catch(() => {
        localStorage.removeItem(AUTH_TOKEN_KEY);
        localStorage.removeItem(AUTH_OFFICER_KEY);
        setAuthenticated(false);
        setOfficer(null);
      })
      .finally(() => setAuthChecking(false));
  }, []);

  const [currentPage, setCurrentPage] =
    useState("dashboard");

  const [selectedFile, setSelectedFile] =
    useState(null);

  const [referencePhoto, setReferencePhoto] =
    useState(null);

  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const videoRef = useRef(null);
  const cameraStreamRef = useRef(null);

  const [referencePreviewUrl, setReferencePreviewUrl] =
    useState(null);

  const [previewUrl, setPreviewUrl] =
    useState(null);

  const [analysisResult, setAnalysisResult] =
    useState(null);

  const [isAnalyzing, setIsAnalyzing] =
    useState(false);

  const [analysisError, setAnalysisError] =
    useState("");

  const [history, setHistory] =
    useState([]);

  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");

  const [historySearch, setHistorySearch] =
    useState("");

  const [historyFilter, setHistoryFilter] =
    useState("ALL");

  const [selectedHistoryRecord, setSelectedHistoryRecord] =
    useState(null);

  const [analyticsData, setAnalyticsData] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState("");

  const [reportData, setReportData] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState("");
  const [reportStatusFilter, setReportStatusFilter] = useState("ALL");
  const [reportTypeFilter, setReportTypeFilter] = useState("ALL");

  const [auditLogs, setAuditLogs] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState("");
  const [auditSearch, setAuditSearch] = useState("");
  const [auditFilter, setAuditFilter] = useState("ALL");


  /* =======================================================
     LOAD AUDIT TRAIL FROM MONGODB THROUGH FASTAPI
  ======================================================= */
  const loadAuditLogs = async () => {
    setAuditLoading(true);
    setAuditError("");
    try {
      const response = await authFetch(`${API_BASE_URL}/audit-logs?limit=200`);
      if (!response.ok) {
        throw new Error(`Audit endpoint returned ${response.status}`);
      }
      const data = await response.json();
      setAuditLogs(Array.isArray(data?.logs) ? data.logs : []);
    } catch (error) {
      console.error("Audit trail loading failed:", error);
      setAuditError("Unable to load audit trail from MongoDB.");
    } finally {
      setAuditLoading(false);
    }
  };

  useEffect(() => {
    if (currentPage === "audit") {
      loadAuditLogs();
    }
  }, [currentPage]);

  const filteredAuditLogs = useMemo(() => {
    const query = auditSearch.trim().toLowerCase();
    return auditLogs.filter((log) => {
      const event = String(log?.event || "").toUpperCase();
      const matchesFilter = auditFilter === "ALL" || event === auditFilter;
      const officerName = log?.officer?.name || "";
      const username = log?.officer?.username || "";
      const caseId = log?.case_id || "";
      const details = JSON.stringify(log?.details || {});
      const haystack = `${event} ${officerName} ${username} ${caseId} ${details}`.toLowerCase();
      return matchesFilter && (!query || haystack.includes(query));
    });
  }, [auditLogs, auditFilter, auditSearch]);

  /* =======================================================
     LOAD HISTORY FROM MONGODB THROUGH FASTAPI
  ======================================================= */

  const loadBackendHistory = async () => {
    setHistoryLoading(true);
    setHistoryError("");

    try {
      const response = await authFetch(`${API_BASE_URL}/history`);

      if (!response.ok) {
        throw new Error(`History endpoint returned ${response.status}`);
      }

      const data = await response.json();
      const records = getHistoryFromResponse(data);

      setHistory(
        records.map((record, index) =>
          normalizeHistoryRecord(record, index)
        )
      );
    } catch (error) {
      console.error("History loading failed:", error);
      setHistoryError(
        "Unable to load screening history from MongoDB."
      );
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (authenticated) {
      loadBackendHistory();
    }
  }, [authenticated]);

  /* =======================================================
     LOAD LIVE ANALYTICS FROM MONGODB THROUGH FASTAPI
  ======================================================= */

  const loadAnalytics = async () => {
    setAnalyticsLoading(true);
    setAnalyticsError("");

    try {
      const response = await authFetch(`${API_BASE_URL}/analytics`);

      if (!response.ok) {
        throw new Error(`Analytics endpoint returned ${response.status}`);
      }

      const data = await response.json();
      setAnalyticsData(data);
    } catch (error) {
      console.error("Analytics loading failed:", error);
      setAnalyticsError(
        "Unable to load live risk analytics from MongoDB."
      );
    } finally {
      setAnalyticsLoading(false);
    }
  };

  useEffect(() => {
    if (currentPage === "analytics") {
      loadAnalytics();
    }
  }, [currentPage]);

  /* =======================================================
     LOAD LIVE REPORTS FROM MONGODB
  ======================================================= */

  const loadReports = async () => {
    setReportLoading(true);
    setReportError("");

    try {
      const params = new URLSearchParams({
        status: reportStatusFilter,
        document_type: reportTypeFilter,
        limit: "500",
      });

      const response = await authFetch(`${API_BASE_URL}/reports?${params.toString()}`);

      if (!response.ok) {
        throw new Error(`Reports endpoint returned ${response.status}`);
      }

      const data = await response.json();
      setReportData(data);
    } catch (error) {
      console.error("Reports loading failed:", error);
      setReportError("Unable to load reports from MongoDB.");
    } finally {
      setReportLoading(false);
    }
  };

  useEffect(() => {
    if (currentPage === "reports") {
      loadReports();
    }
  }, [currentPage, reportStatusFilter, reportTypeFilter]);

  const exportReportCSV = () => {
    const rows = reportData?.reports || [];
    const headers = [
      "Case ID", "Date", "Document Type", "Name", "DOB", "Document ID",
      "Validity", "Status", "Risk Score", "Risk Level", "Reference Status"
    ];

    const csvRows = rows.map((record) => [
      record.case_id || "",
      record.screened_at || "",
      record.document_type || "",
      record.name || "",
      record.date_of_birth || "",
      record.id_number || "",
      record.validity || "",
      record.screening_status || "",
      record.risk_assessment?.score ?? "",
      record.risk_assessment?.level || "",
      record.reference_verification?.status || "NOT_CHECKED",
    ]);

    const escapeCSV = (value) => `"${String(value).replace(/"/g, '""')}"`;
    const csv = [headers, ...csvRows].map((row) => row.map(escapeCSV).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `veriguard-screening-report-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const exportReportJSON = () => {
    const payload = {
      generated_at: new Date().toISOString(),
      filters: { status: reportStatusFilter, document_type: reportTypeFilter },
      summary: reportData?.summary || {},
      reports: reportData?.reports || [],
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `veriguard-screening-report-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };


  /* =======================================================
     CLEAN PREVIEW URL
  ======================================================= */

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
      if (referencePreviewUrl) {
        URL.revokeObjectURL(referencePreviewUrl);
      }
    };
  }, [previewUrl, referencePreviewUrl]);


  /* =======================================================
     FILE SELECT
  ======================================================= */

  const handleFileSelect = (file) => {
    if (!file) {
      return;
    }

    setAnalysisResult(null);
    setAnalysisError("");
    setSelectedFile(file);

    if (file.type.startsWith("image/")) {
      const url = URL.createObjectURL(file);
      setPreviewUrl(url);
    } else {
      setPreviewUrl(null);
    }
  };


  const handleReferencePhotoSelect = (file) => {
    if (!file) return;
    setReferencePhoto(file);
    setCameraError("");
    if (referencePreviewUrl) URL.revokeObjectURL(referencePreviewUrl);
    setReferencePreviewUrl(file.type.startsWith("image/") ? URL.createObjectURL(file) : null);
  };

  const openCamera = async () => {
    setCameraError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Camera is not supported by this browser.");
      }
      if (cameraStreamRef.current) {
        cameraStreamRef.current.getTracks().forEach((track) => track.stop());
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      cameraStreamRef.current = stream;
      setCameraOpen(true);
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
      }, 50);
    } catch (error) {
      setCameraError(error?.message || "Unable to access camera. Please allow camera permission or upload a photo.");
      setCameraOpen(false);
    }
  };

  const closeCamera = () => {
    if (cameraStreamRef.current) {
      cameraStreamRef.current.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
    }
    setCameraOpen(false);
  };

  const capturePersonPhoto = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth || !video.videoHeight) {
      setCameraError("Camera is not ready yet. Please wait a moment.");
      return;
    }
    // Capture only the central guided region so background faces are not sent
    // to the face-verification model. The blue oval in the camera UI marks
    // the intended subject area.
    const sourceWidth = video.videoWidth;
    const sourceHeight = video.videoHeight;
    const cropWidth = Math.round(sourceWidth * 0.64);
    const cropHeight = Math.round(sourceHeight * 0.82);
    const cropX = Math.max(0, Math.round((sourceWidth - cropWidth) / 2));
    const cropY = Math.max(0, Math.round((sourceHeight - cropHeight) / 2));

    const canvas = document.createElement("canvas");
    canvas.width = cropWidth;
    canvas.height = cropHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(
      video,
      cropX, cropY, cropWidth, cropHeight,
      0, 0, cropWidth, cropHeight
    );
    canvas.toBlob((blob) => {
      if (!blob) return;
      const file = new File([blob], `person-photo-${Date.now()}.jpg`, { type: "image/jpeg" });
      handleReferencePhotoSelect(file);
      closeCamera();
    }, "image/jpeg", 0.92);
  };


  /* =======================================================
     REMOVE FILE
  ======================================================= */

  const handleRemoveFile = () => {
    setSelectedFile(null);
    setPreviewUrl(null);
    setReferencePhoto(null);
    setReferencePreviewUrl(null);
    setCameraOpen(false);
    setCameraError("");
    if (cameraStreamRef.current) {
      cameraStreamRef.current.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
    }
    setAnalysisResult(null);
    setAnalysisError("");
  };


  /* =======================================================
     NEW SCREENING
  ======================================================= */

  const handleNewScreening = () => {
    setSelectedFile(null);
    setPreviewUrl(null);
    setReferencePhoto(null);
    setReferencePreviewUrl(null);
    setAnalysisResult(null);
    setAnalysisError("");
    setIsAnalyzing(false);
    setCurrentPage("screening");
  };


  /* =======================================================
     ANALYZE DOCUMENT
  ======================================================= */

  const handleAnalyze = async () => {

    if (!selectedFile) {
      setAnalysisError("Please upload a document first.");
      return;
    }

    if (!referencePhoto) {
      setAnalysisError("Please take or upload the person's photo. Face matching requires both the document and person photo.");
      return;
    }

    setIsAnalyzing(true);
    setAnalysisResult(null);
    setAnalysisError("");

    const formData = new FormData();

    formData.append(
      "file",
      selectedFile
    );

    if (referencePhoto) {
      formData.append(
        "person_photo",
        referencePhoto
      );
    }

    try {

      const response = await authFetch(
        `${API_BASE_URL}/upload`,
        {
          method: "POST",
          body: formData,
        }
      );

      if (!response.ok) {
        throw new Error(
          `Backend returned ${response.status}`
        );
      }

      const data =
        await response.json();

      setAnalysisResult(data);


      /* ==============================================
         REFRESH HISTORY FROM MONGODB
      ============================================== */

      await loadBackendHistory();

    } catch (error) {

      console.error(
        "Document analysis failed:",
        error
      );

      setAnalysisError(
        "Unable to connect to the screening server. Make sure FastAPI backend is running on port 8000."
      );

    } finally {

      setIsAnalyzing(false);

    }
  };


  /* =======================================================
     RESULT DATA
  ======================================================= */

  const ocrText =
    analysisResult?.extracted_text ||
    analysisResult?.ocr_text ||
    "";


  const ocrIdentity =
    extractIdentityFromOCR(ocrText);


  const documentType =
    getFirstAvailable(
      analysisResult?.document_type,
      analysisResult?.document?.type,
      "Document"
    );


  const identityName =
    getFirstAvailable(
      getNestedValue(
        analysisResult,
        [
          "name",
          "full_name",
          "extracted_fields.name",
          "extracted_data.name",
          "fields.name",
          "identity.name",
        ]
      ),
      ocrIdentity.name,
      "Not detected"
    );


  const identityDob =
    getFirstAvailable(
      getNestedValue(
        analysisResult,
        [
          "date_of_birth",
          "dob",
          "extracted_fields.date_of_birth",
          "extracted_fields.dob",
          "extracted_data.date_of_birth",
          "fields.date_of_birth",
          "identity.date_of_birth",
        ]
      ),
      ocrIdentity.dob,
      "Not detected"
    );


  const identityId =
    getFirstAvailable(
      getNestedValue(
        analysisResult,
        [
          "id_number",
          "document_number",
          "passport_number",
          "extracted_fields.id_number",
          "extracted_fields.document_number",
          "extracted_data.id_number",
          "fields.id_number",
          "identity.id_number",
        ]
      ),
      ocrIdentity.idNumber,
      "Not detected"
    );


  const identityValidity =
    getFirstAvailable(
      getNestedValue(
        analysisResult,
        [
          "validity",
          "expiry",
          "expiry_date",
          "extracted_fields.validity",
          "extracted_fields.expiry",
          "extracted_data.validity",
          "fields.validity",
          "identity.validity",
        ]
      ),
      ocrIdentity.validity,
      "Not detected"
    );


  const validationStatus =
    getFirstAvailable(
      getNestedValue(
        analysisResult,
        [
          "validation.status",
          "document_validation.status",
          "validation_result.status",
        ]
      ),
      "Processed"
    );


  const tampering =
    analysisResult?.tampering_analysis || {};


  const tamperingScore =
    Number(tampering.score ?? 0);


  const tamperingConfidence =
    tampering.confidence || "LOW";


  const screeningRisk =
    analysisResult?.risk_assessment || {};


  const screeningRiskScore =
    Number(screeningRisk.score ?? 0);


  const screeningRiskLevel =
    screeningRisk.level || getRiskStatus(screeningRiskScore);


  const screeningRiskDecision =
    screeningRisk.recommendation || screeningRisk.decision || "CLEAR";


  const screeningRiskConfidence =
    screeningRisk.confidence || "LOW";


  const riskContributors =
    Array.isArray(screeningRisk.contributors)
      ? screeningRisk.contributors
      : [];


  const tamperingIndicators =
    Array.isArray(tampering.indicators)
      ? tampering.indicators
      : [];


  const components =
    tampering.components || {};


  const elaStatus =
    components?.ela?.status ||
    "NOT AVAILABLE";


  const textConsistencyStatus =
    components?.text_consistency?.status ||
    "NOT AVAILABLE";


  const localRegionStatus =
    components?.local_regions?.status ||
    "NOT AVAILABLE";


  const metadataStatus =
    components?.metadata?.status ||
    "NOT AVAILABLE";


  /* =======================================================
     HISTORY FILTER
  ======================================================= */

  const filteredHistory = useMemo(() => {

    return history.filter((record) => {

      const matchesSearch =
        record.caseId
          ?.toLowerCase()
          .includes(historySearch.toLowerCase()) ||
        record.documentType
          ?.toLowerCase()
          .includes(historySearch.toLowerCase()) ||
        record.filename
          ?.toLowerCase()
          .includes(historySearch.toLowerCase());


      const matchesFilter =
        historyFilter === "ALL" ||
        record.status === historyFilter;


      return matchesSearch && matchesFilter;

    });

  }, [
    history,
    historySearch,
    historyFilter,
  ]);


  if (authChecking) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#071019",
          color: "#e9f1f6",
        }}
      >
        <div style={{ textAlign: "center", opacity: 0.7 }}>
          <Loader2 size={24} className="loading-icon" />
          <div style={{ marginTop: "10px", fontSize: "12px" }}>Checking secure session...</div>
        </div>
      </div>
    );
  }

  if (!authenticated) {
    return <LoginScreen onLogin={handleLogin} theme={theme} onToggleTheme={toggleTheme} />;
  }

  /* =======================================================
     DASHBOARD STATS
  ======================================================= */

  const totalScreened =
    history.length;

  const verifiedCount =
    history.filter(
      (item) => item.status === "VERIFIED"
    ).length;

  const reviewCount =
    history.filter(
      (item) => item.status === "REVIEW"
    ).length;

  const highRiskCount =
    history.filter(
      (item) => item.status === "HIGH RISK"
    ).length;


  /* =======================================================
     RENDER
  ======================================================= */

  return (

    <div className="app">

      {/* =================================================
          SIDEBAR
      ================================================= */}

      <aside className="sidebar">

        <div className="brand">

          <div className="brand-icon">
            <ShieldCheck size={22} />
          </div>

          <div>
            <h1>VERIGUARD</h1>
            <span>Identity Security</span>
          </div>

        </div>


        <nav className="navigation">

          <p className="nav-title">
            MAIN
          </p>


          <button
            className={`nav-item ${
              currentPage === "dashboard"
                ? "active"
                : ""
            }`}
            onClick={() =>
              setCurrentPage("dashboard")
            }
          >
            <LayoutDashboard size={19} />
            <span>Dashboard</span>
          </button>


          <button
            className={`nav-item ${
              currentPage === "screening"
                ? "active"
                : ""
            }`}
            onClick={() =>
              setCurrentPage("screening")
            }
          >
            <ScanSearch size={19} />
            <span>Document Screening</span>
          </button>


          <button
            className={`nav-item ${
              currentPage === "history"
                ? "active"
                : ""
            }`}
            onClick={() =>
              setCurrentPage("history")
            }
          >
            <FileSearch size={19} />
            <span>Screening History</span>
          </button>


          <p className="nav-title">
            ANALYTICS
          </p>


          <button
            className={`nav-item ${
              currentPage === "analytics"
                ? "active"
                : ""
            }`}
            onClick={() =>
              setCurrentPage("analytics")
            }
          >
            <BarChart3 size={19} />
            <span>Risk Analytics</span>
          </button>


          <button
            className={`nav-item ${
              currentPage === "reports"
                ? "active"
                : ""
            }`}
            onClick={() =>
              setCurrentPage("reports")
            }
          >
            <FileText size={19} />
            <span>Reports</span>
          </button>

        </nav>


        <div className="sidebar-bottom">

          <button
            className={`nav-item ${
              currentPage === "settings"
                ? "active"
                : ""
            }`}
            onClick={() => setCurrentPage("settings")}
          >
            <Settings size={19} />
            <span>Settings</span>
          </button>

          <button className="nav-item">
            <HelpCircle size={19} />
            <span>Help & Support</span>
          </button>


          <div className="system-status">

            <div className="status-dot"></div>

            <div>
              <strong>
                System Operational
              </strong>

              <span>
                All services running
              </span>
            </div>

          </div>

        </div>

      </aside>


      {/* =================================================
          MAIN
      ================================================= */}

      <main className="main-area">


        {/* TOPBAR */}

        <header className="topbar">

          <div>

            <span className="topbar-label">
              SECURITY OPERATIONS
            </span>

            <h2>
              Document Security Operations
            </h2>

          </div>


          <div className="topbar-right">

            <div className="system-indicator">
              <Activity size={17} />
              <span>System Online</span>
            </div>


            <button
              type="button"
              className="theme-toggle"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </button>

            <div
              className="profile profile-clickable"
              role="button"
              tabIndex={0}
              title="Open officer profile settings"
              onClick={() => setCurrentPage("settings")}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setCurrentPage("settings");
                }
              }}
              style={{ cursor: "pointer" }}
            >

              <div className="profile-avatar">
                {(officer?.name || officer?.username || "SO")
                  .split(" ")
                  .map((part) => part[0])
                  .join("")
                  .slice(0, 2)
                  .toUpperCase()}
              </div>

              <div className="profile-info">
                <strong>
                  {officer?.name || officer?.username || "Security Officer"}
                </strong>

                <span>
                  {officer?.designation || "Authorized Officer"}
                </span>
              </div>

              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  handleLogout();
                }}
                title="Sign out"
                style={{
                  border: "1px solid rgba(255,255,255,0.08)",
                  background: "rgba(255,255,255,0.03)",
                  color: "inherit",
                  borderRadius: "8px",
                  padding: "7px 9px",
                  cursor: "pointer",
                  fontSize: "11px",
                }}
              >
                Sign out
              </button>

            </div>

          </div>

        </header>


        {/* CONTENT */}

        <section className="content">


          {/* =================================================
              DASHBOARD
          ================================================= */}

          {currentPage === "dashboard" && (

            <>

              <div className="welcome">

                <div>

                  <p className="eyebrow">
                    OVERVIEW
                  </p>

                  <h3>
                    Security screening dashboard
                  </h3>

                  <p>
                    Monitor document verification,
                    integrity analysis and screening
                    risk from one workspace.
                  </p>

                </div>


                <button
                  className="primary-button"
                  onClick={handleNewScreening}
                >
                  <ScanLine size={17} />
                  New Screening
                </button>

              </div>


              {/* STATS */}

              <div className="stats-grid">

                <div className="stat-card">

                  <div className="stat-top">
                    <span>
                      DOCUMENTS SCREENED
                    </span>

                    <ScanSearch size={18} />
                  </div>

                  <strong>
                    {totalScreened}
                  </strong>

                  <p>
                    Total screening records
                  </p>

                </div>


                <div className="stat-card">

                  <div className="stat-top">
                    <span>VERIFIED</span>
                    <ShieldCheck size={18} />
                  </div>

                  <strong>
                    {verifiedCount}
                  </strong>

                  <p>
                    Low-risk screening cases
                  </p>

                </div>


                <div className="stat-card">

                  <div className="stat-top">
                    <span>REVIEW REQUIRED</span>
                    <FileSearch size={18} />
                  </div>

                  <strong>
                    {reviewCount}
                  </strong>

                  <p>
                    Requires officer review
                  </p>

                </div>


                <div className="stat-card">

                  <div className="stat-top">
                    <span>HIGH RISK</span>
                    <ShieldAlert size={18} />
                  </div>

                  <strong>
                    {highRiskCount}
                  </strong>

                  <p>
                    Priority screening cases
                  </p>

                </div>

              </div>


              {/* DASHBOARD LOWER */}

              <div className="dashboard-grid">


                {/* RECENT */}

                <div className="dashboard-panel">

                  <div className="panel-header">

                    <div>
                      <span className="panel-label">
                        SCREENING ACTIVITY
                      </span>

                      <h4>
                        Recent Screening
                      </h4>
                    </div>

                    <button
                      className="text-button"
                      onClick={() =>
                        setCurrentPage("history")
                      }
                    >
                      View all
                    </button>

                  </div>


                  <div className="activity-list">

                    {history
                      .slice(0, 5)
                      .map((item) => (

                        <div
                          className="activity-row"
                          key={item.caseId}
                        >

                          <div className="activity-icon">
                            <FileText size={17} />
                          </div>


                          <div className="activity-info">

                            <strong>
                              {item.caseId}
                            </strong>

                            <span>
                              {item.documentType}
                            </span>

                          </div>


                          <span
                            className={`result ${getRiskClass(
                              item.riskScore
                            )}`}
                          >
                            {item.status}
                          </span>


                          <span className="activity-time">
                            {item.time}
                          </span>

                        </div>

                      ))}

                  </div>

                </div>


                {/* SERVICE STATUS */}

                <div className="dashboard-panel">

                  <div className="panel-header">

                    <div>

                      <span className="panel-label">
                        SYSTEM
                      </span>

                      <h4>
                        Service Status
                      </h4>

                    </div>

                  </div>


                  <div className="service-list">

                    <Service
                      name="OCR Engine"
                      description="Text extraction service"
                      status="Operational"
                    />

                    <Service
                      name="Document Validator"
                      description="Field validation service"
                      status="Operational"
                    />

                    <Service
                      name="Integrity Engine"
                      description="Tampering analysis service"
                      status="Operational"
                    />

                    <Service
                      name="Face Verification"
                      description="Identity matching service"
                      status="Operational"
                    />

                    <Service
                      name="MongoDB"
                      description="Reference and screening database"
                      status={historyError ? "Check" : "Operational"}
                      standby={Boolean(historyError)}
                    />

                  </div>

                </div>

              </div>

            </>

          )}


          {/* =================================================
              DOCUMENT SCREENING
          ================================================= */}

          {currentPage === "screening" && (

            <>

              <div className="welcome">

                <div>

                  <p className="eyebrow">
                    DOCUMENT SCREENING
                  </p>

                  <h3>
                    Screen a document
                  </h3>

                  <p>
                    Upload an identity or travel
                    document for automated security
                    screening.
                  </p>

                </div>

              </div>


              <div className="screening-workspace">


                {/* UPLOAD */}

                <div className="upload-panel">

                  <input
                    type="file"
                    id="document-upload"
                    accept="image/*"
                    hidden
                    onChange={(event) =>
                      handleFileSelect(
                        event.target.files[0]
                      )
                    }
                  />


                  {!selectedFile && (

                    <>

                      <div className="upload-icon">
                        <UploadCloud size={30} />
                      </div>

                      <h3>
                        Upload document
                      </h3>

                      <p>
                        Select a passport, identity
                        card, visa or other document
                        image.
                      </p>

                      <label
                        htmlFor="document-upload"
                        className="browse-button"
                      >
                        Browse files
                      </label>

                      <div className="supported-files">
                        Supported formats:

                        <span>JPG</span>
                        <span>PNG</span>
                        <span>JPEG</span>
                      </div>

                    </>

                  )}


                  {selectedFile && (

                    <div className="selected-file-area">


                      <div className="large-file-preview">

                        {previewUrl ? (

                          <img
                            src={previewUrl}
                            alt="Selected document"
                          />

                        ) : (

                          <div className="pdf-preview">
                            <FileText size={42} />
                            <span>
                              DOCUMENT
                            </span>
                          </div>

                        )}

                      </div>


                      <div className="selected-file-info">

                        <div className="file-type-icon">

                          {previewUrl ? (
                            <ImageIcon size={18} />
                          ) : (
                            <FileText size={18} />
                          )}

                        </div>


                        <div className="file-details">

                          <strong>
                            {selectedFile.name}
                          </strong>

                          <span>
                            {selectedFile.type ||
                              "Unknown type"}
                          </span>

                          <span>
                            {(
                              selectedFile.size / 1024
                            ).toFixed(1)} KB
                          </span>

                        </div>


                        <button
                          className="remove-file"
                          onClick={handleRemoveFile}
                        >
                          <X size={17} />
                        </button>

                      </div>


                      <div
                        style={{
                          marginTop: "16px",
                          padding: "16px",
                          border: "1px solid rgba(255,255,255,0.08)",
                          borderRadius: "12px",
                          background: "rgba(255,255,255,0.02)",
                        }}
                      >
                        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:"12px",flexWrap:"wrap"}}>
                          <div>
                            <strong style={{display:"block"}}>Person Face — choose live scan or upload</strong>
                            <span style={{fontSize:"12px",opacity:0.7}}>Option A: scan your face live with the camera, or Option B: upload a clear face photo. YuNet detects the face and SFace compares it with the document photo.</span>
                          </div>
                          <div style={{display:"flex",gap:"8px",flexWrap:"wrap"}}>
                            <button type="button" className="browse-button" onClick={openCamera}>
                              <Camera size={15} style={{verticalAlign:"middle",marginRight:"5px"}} />
                              Open Camera
                            </button>
                            <label htmlFor="reference-photo-upload" className="browse-button">
                              {referencePhoto ? "Change Uploaded Photo" : "Upload Face Photo"}
                            </label>
                          </div>
                        </div>
                        <input
                          id="reference-photo-upload"
                          type="file"
                          accept="image/*"
                          hidden
                          onChange={(event) => handleReferencePhotoSelect(event.target.files[0])}
                        />

                        {cameraOpen && (
                          <div style={{marginTop:"14px",padding:"12px",borderRadius:"12px",background:"#050b12",border:"1px solid rgba(255,255,255,0.08)"}}>
                            <div style={{position:"relative",width:"100%",height:"min(62vw, 430px)",minHeight:"300px",overflow:"hidden",borderRadius:"10px",background:"#02060a"}}>
                              <video ref={videoRef} autoPlay playsInline muted style={{width:"100%",height:"100%",objectFit:"cover",display:"block",transform:"scaleX(-1)"}} />

                              {/* LIVE FACE ALIGNMENT GUIDE — visual capture zone */}
                              <div style={{position:"absolute",inset:0,pointerEvents:"none"}}>
                                <div style={{position:"absolute",inset:0,background:"radial-gradient(ellipse 27% 43% at 50% 48%, transparent 0%, transparent 66%, rgba(2,6,10,.46) 68%, rgba(2,6,10,.72) 100%)"}} />

                                <div style={{position:"absolute",left:"50%",top:"48%",width:"min(42vw,310px)",height:"min(58vw,390px)",minWidth:"220px",minHeight:"270px",transform:"translate(-50%,-50%)",border:"3px solid #2388ff",borderRadius:"50%",boxShadow:"0 0 0 1px rgba(35,136,255,.25), 0 0 28px rgba(35,136,255,.28), inset 0 0 24px rgba(35,136,255,.08)"}}>
                                  <div style={{position:"absolute",inset:"9px",border:"2px dashed rgba(255,255,255,.65)",borderRadius:"50%"}} />
                                </div>

                                <div style={{position:"absolute",top:"14px",left:"14px",padding:"10px 13px",borderRadius:"10px",background:"rgba(4,12,22,.78)",backdropFilter:"blur(8px)",color:"#fff",fontSize:"12px",lineHeight:1.55,border:"1px solid rgba(255,255,255,.12)"}}>
                                  <strong style={{display:"block",fontSize:"13px",marginBottom:"3px"}}>Live Face Verification</strong>
                                  <span>Keep your face inside the blue guide</span><br />
                                  <span>Look at the camera • good lighting</span>
                                </div>

                                <div style={{position:"absolute",top:"14px",right:"14px",display:"flex",alignItems:"center",gap:"7px",padding:"8px 11px",borderRadius:"999px",background:"rgba(4,12,22,.78)",backdropFilter:"blur(8px)",border:"1px solid rgba(93,211,158,.35)",color:"#9ff0c5",fontSize:"12px"}}>
                                  <span style={{width:"8px",height:"8px",borderRadius:"50%",background:"#5dd39e",boxShadow:"0 0 10px rgba(93,211,158,.7)"}} />
                                  CAMERA LIVE
                                </div>

                                <div style={{position:"absolute",left:"50%",bottom:"14px",transform:"translateX(-50%)",padding:"8px 14px",borderRadius:"999px",background:"rgba(4,12,22,.82)",border:"1px solid rgba(35,136,255,.45)",color:"#dcecff",fontSize:"12px",whiteSpace:"nowrap"}}>
                                  Align your face inside the guide
                                </div>
                              </div>
                            </div>

                            <div style={{display:"flex",alignItems:"center",gap:"8px",marginTop:"10px",fontSize:"12px",color:"#7ee2ae"}}>
                              <span style={{width:"8px",height:"8px",borderRadius:"50%",background:"#5dd39e",boxShadow:"0 0 10px rgba(93,211,158,.55)"}} />
                              Camera active • YuNet will detect the face after capture • SFace will verify against the document portrait
                            </div>
                            <div style={{display:"flex",gap:"8px",marginTop:"10px",flexWrap:"wrap"}}>
                              <button type="button" className="analyze-button" onClick={capturePersonPhoto}>
                                <ScanSearch size={16} /> Capture & Scan Face
                              </button>
                              <button type="button" className="browse-button" onClick={closeCamera}>
                                <VideoOff size={15} /> Close Camera
                              </button>
                            </div>
                          </div>
                        )}

                        {cameraError && (
                          <div style={{marginTop:"10px",fontSize:"12px",color:"#ffb4b4"}}>{cameraError}</div>
                        )}

                        {referencePhoto && (
                          <div style={{display:"flex",alignItems:"center",gap:"12px",marginTop:"12px"}}>
                            {referencePreviewUrl && (
                              <img src={referencePreviewUrl} alt="Person face preview" style={{width:"72px",height:"72px",objectFit:"cover",borderRadius:"10px",border:"1px solid rgba(255,255,255,0.12)"}} />
                            )}
                            <div>
                              <strong style={{display:"block",fontSize:"13px"}}>Person face ready for verification</strong>
                              <span style={{fontSize:"12px",opacity:0.7}}>{referencePhoto.name} • YuNet + SFace verification</span>
                            </div>
                          </div>
                        )}
                      </div>


                      <button
                        className="analyze-button"
                        onClick={handleAnalyze}
                        disabled={isAnalyzing || !selectedFile || !referencePhoto}
                      >

                        {isAnalyzing ? (

                          <>
                            <Loader2
                              size={17}
                              className="loading-icon"
                            />

                            Analyzing Document...
                          </>

                        ) : (

                          <>
                            <ScanLine size={17} />
                            Analyze Document
                          </>

                        )}

                      </button>


                      {analysisError && (

                        <div className="analysis-error">

                          <AlertTriangle size={16} />

                          <span>
                            {analysisError}
                          </span>

                        </div>

                      )}

                    </div>

                  )}

                </div>


                {/* PIPELINE */}

                <div className="screening-info-panel">

                  <div className="panel-label">
                    SCREENING PIPELINE
                  </div>

                  <h4>
                    Automated document analysis
                  </h4>


                  <div className="pipeline-list">

                    <Pipeline
                      number="01"
                      title="OCR Extraction"
                      description="Extract identity fields from document image"
                    />

                    <Pipeline
                      number="02"
                      title="Document Validation"
                      description="Check extracted information and document rules"
                    />

                    <Pipeline
                      number="03"
                      title="Integrity Analysis"
                      description="Identify possible image or text manipulation"
                    />

                    <Pipeline
                      number="04"
                      title="Face Verification"
                      description="Compare only the face printed on the document with the person photo captured/uploaded above"
                    />

                    <Pipeline
                      number="05"
                      title="Risk Assessment"
                      description="Generate officer-facing screening assessment"
                    />

                  </div>

                </div>

              </div>


              {/* RESULT */}

              {analysisResult && (

                <div className="analysis-result">

                  <div className="result-header">

                    <div>

                      <span className="panel-label">
                        SCREENING RESULT
                      </span>

                      <h3>
                        Document analysis completed
                      </h3>

                    </div>


                    <div className="result-complete">
                      <CheckCircle2 size={15} />
                      Analysis Complete
                    </div>

                  </div>


                  {/* IDENTITY */}

                  <div className="result-summary">

                    <ResultItem
                      label="DOCUMENT TYPE"
                      value={documentType}
                    />

                    <ResultItem
                      label="FULL NAME"
                      value={identityName}
                    />

                    <ResultItem
                      label="DATE OF BIRTH"
                      value={identityDob}
                    />

                    <ResultItem
                      label="DOCUMENT ID"
                      value={identityId}
                    />

                    <ResultItem
                      label="VALIDITY"
                      value={identityValidity}
                    />

                    <ResultItem
                      label="VALIDATION"
                      value={validationStatus}
                    />

                  </div>


                  {/* RISK */}

                  <div className="risk-assessment-card">

                    <div className="risk-assessment-header">

                      <div>

                        <span className="panel-label">
                          DOCUMENT RISK ASSESSMENT
                        </span>

                        <h4>
                          Screening Risk
                        </h4>

                      </div>


                      <div className="risk-engine-label">
                        <Activity size={14} />
                        Integrity Engine
                      </div>

                    </div>


                    <div className="risk-main">

                      <div className="risk-score-area">

                        <span className="risk-score-label">
                          RISK SCORE
                        </span>

                        <div className="risk-score">

                          <strong>
                            {screeningRiskScore}
                          </strong>

                          <span>
                            / 100
                          </span>

                        </div>

                        <span className="risk-confidence">
                          Confidence: {screeningRiskConfidence}
                        </span>

                      </div>


                      <div className="risk-status-area">

                        <div
                          className={`risk-status-badge ${getRiskClass(
                            screeningRiskScore
                          )}`}
                        >

                          {tamperingScore >= 60 ? (
                            <ShieldAlert size={17} />
                          ) : tamperingScore >= 35 ? (
                            <AlertTriangle size={17} />
                          ) : (
                            <ShieldCheck size={17} />
                          )}

                          <span>
                            {screeningRiskLevel}
                          </span>

                        </div>


                        <p>

                          {screeningRiskScore >= 80
                            ? "Critical risk: reject and escalate for officer review."
                            : screeningRiskScore >= 60
                            ? "High risk: manual officer review is required."
                            : screeningRiskScore >= 35
                            ? "Medium risk: additional verification is recommended."
                            : screeningRiskScore >= 20
                            ? "Low risk with review flag: perform a secondary check."
                            : "Current screening signals indicate a low-risk case."}

                        </p>

                      </div>

                    </div>


                    <div className="risk-meter">

                      <div className="risk-meter-track">

                        <div
                          className={`risk-meter-fill ${getRiskClass(
                            screeningRiskScore
                          )}`}
                          style={{
                            width: `${Math.min(
                              screeningRiskScore,
                              100
                            )}%`,
                          }}
                        />

                      </div>


                      <div className="risk-meter-scale">
                        <span>LOW</span>
                        <span>MEDIUM</span>
                        <span>HIGH</span>
                      </div>

                    </div>


                    <div className="risk-decision-row">

                      <div className="risk-decision-box">
                        <span className="panel-label">SCREENING DECISION</span>
                        <strong>{screeningRiskDecision}</strong>
                      </div>

                      <div className="risk-decision-box">
                        <span className="panel-label">RISK MODEL</span>
                        <strong>{screeningRisk.risk_model || "Structured Multi-Signal v1"}</strong>
                      </div>

                    </div>


                    <div className="risk-contributors-panel">
                      <div className="risk-contributors-header">
                        <div>
                          <span className="panel-label">RISK CONTRIBUTORS</span>
                          <h5>Why this score was generated</h5>
                        </div>
                        <span className="risk-contributor-count">
                          {riskContributors.length} signal{riskContributors.length === 1 ? "" : "s"}
                        </span>
                      </div>

                      {riskContributors.length > 0 ? (
                        <div className="risk-contributor-list">
                          {riskContributors.map((item, index) => (
                            <div className="risk-contributor-item" key={`${item.source}-${index}`}>
                              <div className="risk-contributor-main">
                                <div className="risk-contributor-title">
                                  <span>{item.source}</span>
                                  <strong>+{item.points}</strong>
                                </div>
                                <p>{item.reason}</p>
                              </div>
                              <span className={`risk-severity ${String(item.severity || "INFO").toLowerCase()}`}>
                                {item.severity || "INFO"}
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="risk-clear-message">
                          <ShieldCheck size={15} />
                          No risk contributors were detected. Current signals support a clear screening result.
                        </div>
                      )}
                    </div>


                    <div className="risk-officer-note">

                      <ShieldCheck size={15} />

                      <div>

                        <strong>
                          Officer guidance
                        </strong>

                        <span>
                          Automated screening is a
                          decision-support signal and
                          should not replace officer
                          verification.
                        </span>

                      </div>

                    </div>

                  </div>


                  {/* REFERENCE DATABASE VERIFICATION */}

                  {analysisResult?.reference_verification && (
                    <div className="component-panel">
                      <span className="panel-label">
                        REFERENCE DATABASE
                      </span>

                      <h4>
                        Identity reference verification
                      </h4>

                      <div className="result-summary">
                        <ResultItem
                          label="MATCH STATUS"
                          value={
                            analysisResult.reference_verification.status ||
                            "NOT CHECKED"
                          }
                        />

                        <ResultItem
                          label="MATCHED FIELDS"
                          value={
                            analysisResult.reference_verification
                              .matched_fields?.length ?? 0
                          }
                        />

                        <ResultItem
                          label="MISMATCHED FIELDS"
                          value={
                            analysisResult.reference_verification
                              .mismatched_fields?.length ?? 0
                          }
                        />

                        <ResultItem
                          label="REFERENCE FOUND"
                          value={
                            analysisResult.reference_verification
                              .reference_document
                              ? "YES"
                              : "NO"
                          }
                        />
                      </div>
                    </div>
                  )}


                  {/* FACE VERIFICATION */}

                  {analysisResult?.face_verification && (
                    <div className="component-panel">
                      <span className="panel-label">
                        FACE VERIFICATION
                      </span>

                      <h4>
                        Person ↔ document photo verification
                      </h4>
                      <div style={{marginTop:"6px",fontSize:"11px",opacity:0.65}}>YuNet face detection • SFace face recognition • document photo only</div>

                      <div className="result-summary">
                        <ResultItem
                          label="STATUS"
                          value={analysisResult.face_verification.status || "NOT CHECKED"}
                        />
                        <ResultItem
                          label="SIMILARITY"
                          value={`${analysisResult.face_verification.similarity ?? 0}/100`}
                        />
                        <ResultItem
                          label="DOCUMENT FACE"
                          value={analysisResult.face_verification.document_face_detected ? "DETECTED" : "NOT DETECTED"}
                        />
                        <ResultItem
                          label="PERSON FACE"
                          value={(analysisResult.face_verification.person_face_detected ?? analysisResult.face_verification.reference_face_detected) ? "DETECTED" : "NOT DETECTED"}
                        />
                        <ResultItem
                          label="DETECTED FACES"
                          value={`${analysisResult.face_verification.document_face_count ?? "-"} doc / ${analysisResult.face_verification.person_face_count ?? "-"} person`}
                        />
                      </div>

                      <p style={{marginTop:"12px",opacity:0.75,fontSize:"12px"}}>
                        {analysisResult.face_verification.reason || "Face verification result generated."}
                      </p>
                    </div>
                  )}


                  {/* COMPONENTS */}

                  <div className="component-panel">

                    <div>

                      <span className="panel-label">
                        SCREENING CHECKS
                      </span>

                      <h4>
                        Analysis components
                      </h4>

                    </div>


                    <div className="component-grid">

                      <ComponentCard
                        title="OCR Extraction"
                        value="Completed"
                        icon={<ScanSearch size={15} />}
                        good
                      />

                      <ComponentCard
                        title="Document Validation"
                        value={validationStatus}
                        icon={<CheckCircle2 size={15} />}
                        good
                      />

                      <ComponentCard
                        title="ELA Analysis"
                        value={elaStatus}
                        icon={<ShieldCheck size={15} />}
                      />

                      <ComponentCard
                        title="Text Consistency"
                        value={textConsistencyStatus}
                        icon={<ScanSearch size={15} />}
                      />

                      <ComponentCard
                        title="Local Region Analysis"
                        value={localRegionStatus}
                        icon={<ScanLine size={15} />}
                      />

                      <ComponentCard
                        title="Metadata"
                        value={metadataStatus}
                        icon={<Database size={15} />}
                      />

                    </div>

                  </div>


                  {/* FINDINGS */}

                  {tamperingIndicators.length > 0 && (

                    <div className="component-panel">

                      <span className="panel-label">
                        SCREENING FINDINGS
                      </span>

                      <h4>
                        Review indicators
                      </h4>


                      <div className="findings-list">

                        {tamperingIndicators.map(
                          (indicator, index) => (

                            <div
                              className="finding"
                              key={index}
                            >

                              <ShieldAlert
                                size={15}
                              />

                              <span>
                                {indicator}
                              </span>

                            </div>

                          )
                        )}

                      </div>

                    </div>

                  )}


                  {/* OCR */}

                  {ocrText && (

                    <div className="component-panel">

                      <span className="panel-label">
                        OCR EXTRACTION
                      </span>

                      <h4>
                        Extracted document text
                      </h4>

                      <div className="ocr-text">
                        {ocrText}
                      </div>

                    </div>

                  )}


                  <div className="result-footer">

                    <button
                      className="secondary-button"
                      onClick={handleNewScreening}
                    >
                      <RotateCcw size={15} />
                      New Screening
                    </button>

                  </div>

                </div>

              )}

            </>

          )}


          {/* =================================================
              HISTORY
          ================================================= */}

          {currentPage === "history" && (

            <>

              <PageHeader
                eyebrow="SCREENING HISTORY"
                title="Screening history"
                description="Review previously analyzed identity documents and their screening outcomes."
              />


              <div className="history-toolbar">

                <div className="search-box">

                  <Search size={17} />

                  <input
                    placeholder="Search case ID, document..."
                    value={historySearch}
                    onChange={(event) =>
                      setHistorySearch(
                        event.target.value
                      )
                    }
                  />

                </div>


                <select
                  value={historyFilter}
                  onChange={(event) =>
                    setHistoryFilter(
                      event.target.value
                    )
                  }
                >
                  <option value="ALL">
                    All Status
                  </option>

                  <option value="VERIFIED">
                    Verified
                  </option>

                  <option value="REVIEW">
                    Review
                  </option>

                  <option value="HIGH RISK">
                    High Risk
                  </option>

                </select>

                <button
                  className="secondary-button"
                  onClick={loadBackendHistory}
                  disabled={historyLoading}
                  style={{ marginLeft: "10px" }}
                >
                  <RotateCcw
                    size={15}
                    className={historyLoading ? "loading-icon" : ""}
                  />
                  {historyLoading ? "Loading..." : "Refresh"}
                </button>

              </div>

              {historyError && (
                <div
                  className="analysis-error"
                  style={{ marginBottom: "16px" }}
                >
                  <AlertTriangle size={16} />
                  <span>{historyError}</span>
                </div>
              )}


              <div className="history-panel">

                <div className="history-header-row">

                  <span>CASE ID</span>
                  <span>DOCUMENT</span>
                  <span>RESULT</span>
                  <span>RISK</span>
                  <span>CONFIDENCE</span>
                  <span>TIME</span>

                </div>


                {filteredHistory.length === 0 ? (

                  <div className="empty-state">

                    <FileSearch size={28} />

                    <h4>
                      No screening records
                    </h4>

                    <p>
                      Try another search or analyze
                      a new document.
                    </p>

                  </div>

                ) : (

                  filteredHistory.map((item) => (

                    <div
                      className="history-row"
                      key={item.caseId}
                    >

                      <strong>
                        {item.caseId}
                      </strong>

                      <div className="history-document">

                        <FileText size={16} />

                        <span>
                          {item.documentType}
                        </span>

                      </div>


                      <span
                        className={`result ${getRiskClass(
                          item.riskScore
                        )}`}
                      >
                        {item.status}
                      </span>


                      <strong>
                        {item.riskScore}/100
                      </strong>


                      <span className="confidence-text">
                        {item.confidence}
                      </span>


                      <span className="history-time">
                        <Clock3 size={14} />
                        {item.time}
                      </span>

                      <button
                        className="secondary-button"
                        onClick={() => setSelectedHistoryRecord(item)}
                        style={{
                          padding: "7px 10px",
                          fontSize: "12px",
                          marginLeft: "8px",
                        }}
                      >
                        <Eye size={14} />
                        View
                      </button>

                    </div>

                  ))

                )}

              </div>

            </>

          )}


          {/* =================================================
              ANALYTICS
          ================================================= */}

          {currentPage === "analytics" && (

            <>

              <PageHeader
                eyebrow="RISK ANALYTICS"
                title="Screening risk analytics"
                description="Live screening statistics calculated from MongoDB records."
              />

              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  marginBottom: "16px",
                }}
              >
                <button
                  className="secondary-button"
                  onClick={loadAnalytics}
                  disabled={analyticsLoading}
                >
                  <RotateCcw
                    size={15}
                    className={analyticsLoading ? "loading-icon" : ""}
                  />
                  {analyticsLoading ? "Loading..." : "Refresh Analytics"}
                </button>
              </div>

              {analyticsError && (
                <div className="analysis-error" style={{ marginBottom: "16px" }}>
                  <AlertTriangle size={16} />
                  <span>{analyticsError}</span>
                </div>
              )}

              <div className="analytics-grid">

                <div className="analytics-card">
                  <span>TOTAL CASES</span>
                  <strong>
                    {analyticsData?.total_cases ?? totalScreened}
                  </strong>
                  <p>MongoDB screening records</p>
                </div>

                <div className="analytics-card">
                  <span>VERIFIED RATE</span>
                  <strong>
                    {analyticsData?.verified_rate ?? 0}%
                  </strong>
                  <p>Low-risk verified cases</p>
                </div>

                <div className="analytics-card">
                  <span>REVIEW RATE</span>
                  <strong>
                    {analyticsData?.review_rate ?? 0}%
                  </strong>
                  <p>Manual review cases</p>
                </div>

                <div className="analytics-card">
                  <span>HIGH RISK RATE</span>
                  <strong>
                    {analyticsData?.high_risk_rate ?? 0}%
                  </strong>
                  <p>Priority cases</p>
                </div>

              </div>

              <div className="analytics-grid" style={{ marginTop: "16px" }}>

                <div className="analytics-card">
                  <span>AVERAGE RISK SCORE</span>
                  <strong>
                    {analyticsData?.average_risk_score ?? 0}
                  </strong>
                  <p>Across all screened documents</p>
                </div>

                <div className="analytics-card">
                  <span>REFERENCE MATCH</span>
                  <strong>
                    {analyticsData?.reference_match_count ?? 0}
                  </strong>
                  <p>Reference database matches</p>
                </div>

                <div className="analytics-card">
                  <span>NO MATCH</span>
                  <strong>
                    {analyticsData?.reference_no_match_count ?? 0}
                  </strong>
                  <p>Documents without reference</p>
                </div>

                <div className="analytics-card">
                  <span>PARTIAL / MISMATCH</span>
                  <strong>
                    {(analyticsData?.reference_partial_match_count ?? 0) +
                      (analyticsData?.reference_mismatch_count ?? 0)}
                  </strong>
                  <p>Cases needing additional checks</p>
                </div>

              </div>

              <div className="analytics-panel">

                <div className="panel-header">
                  <div>
                    <span className="panel-label">
                      RISK DISTRIBUTION
                    </span>
                    <h4>Live MongoDB screening profile</h4>
                  </div>
                </div>

                <RiskBar
                  label="Verified"
                  count={analyticsData?.verified_count ?? 0}
                  total={analyticsData?.total_cases ?? 0}
                />

                <RiskBar
                  label="Review Required"
                  count={analyticsData?.review_count ?? 0}
                  total={analyticsData?.total_cases ?? 0}
                />

                <RiskBar
                  label="High Risk"
                  count={analyticsData?.high_risk_count ?? 0}
                  total={analyticsData?.total_cases ?? 0}
                />

              </div>

              <div className="analytics-panel" style={{ marginTop: "16px" }}>

                <div className="panel-header">
                  <div>
                    <span className="panel-label">
                      REFERENCE DATABASE
                    </span>
                    <h4>Reference verification distribution</h4>
                  </div>
                </div>

                <RiskBar
                  label="Reference Match"
                  count={analyticsData?.reference_match_count ?? 0}
                  total={analyticsData?.total_cases ?? 0}
                />

                <RiskBar
                  label="Partial Match"
                  count={analyticsData?.reference_partial_match_count ?? 0}
                  total={analyticsData?.total_cases ?? 0}
                />

                <RiskBar
                  label="Mismatch"
                  count={analyticsData?.reference_mismatch_count ?? 0}
                  total={analyticsData?.total_cases ?? 0}
                />

                <RiskBar
                  label="No Match"
                  count={analyticsData?.reference_no_match_count ?? 0}
                  total={analyticsData?.total_cases ?? 0}
                />

              </div>

              {analyticsData?.document_types &&
                Object.keys(analyticsData.document_types).length > 0 && (
                  <div
                    className="analytics-panel"
                    style={{ marginTop: "16px" }}
                  >
                    <div className="panel-header">
                      <div>
                        <span className="panel-label">
                          DOCUMENT TYPES
                        </span>
                        <h4>Screened document distribution</h4>
                      </div>
                    </div>

                    {Object.entries(analyticsData.document_types).map(
                      ([type, count]) => (
                        <RiskBar
                          key={type}
                          label={type}
                          count={count}
                          total={analyticsData.total_cases ?? 0}
                        />
                      )
                    )}
                  </div>
                )}

            </>

          )}


          {/* =================================================
              AUDIT TRAIL
          ================================================= */}
          {currentPage === "audit" && (
            <>
              <PageHeader
                eyebrow="SECURITY AUDIT"
                title="Audit Trail"
                description="Review authenticated access and screening activity recorded by VERIGUARD."
              />

              <div className="audit-toolbar">
                <div className="search-box audit-search-box">
                  <Search size={15} />
                  <input
                    value={auditSearch}
                    onChange={(event) => setAuditSearch(event.target.value)}
                    placeholder="Search event, officer or case ID..."
                  />
                </div>

                <select value={auditFilter} onChange={(event) => setAuditFilter(event.target.value)}>
                  <option value="ALL">All events</option>
                  <option value="LOGIN_SUCCESS">Login success</option>
                  <option value="LOGIN_FAILED">Login failed</option>
                  <option value="SCREENING_COMPLETED">Screening completed</option>
                  <option value="LOGOUT">Logout</option>
                </select>

                <button type="button" className="secondary-button" onClick={loadAuditLogs} disabled={auditLoading}>
                  {auditLoading ? <Loader2 className="spin" size={15} /> : <RotateCcw size={15} />}
                  Refresh
                </button>
              </div>

              {auditError && <div className="error-box">{auditError}</div>}

              <div className="audit-summary-grid">
                <div className="audit-stat-card"><span>TOTAL EVENTS</span><strong>{auditLogs.length}</strong><p>Recorded security events</p></div>
                <div className="audit-stat-card"><span>SCREENINGS</span><strong>{auditLogs.filter((x) => x?.event === "SCREENING_COMPLETED").length}</strong><p>Completed document checks</p></div>
                <div className="audit-stat-card"><span>AUTH EVENTS</span><strong>{auditLogs.filter((x) => ["LOGIN_SUCCESS", "LOGIN_FAILED", "LOGOUT"].includes(x?.event)).length}</strong><p>Access and session events</p></div>
                <div className="audit-stat-card"><span>VISIBLE</span><strong>{filteredAuditLogs.length}</strong><p>Events matching filters</p></div>
              </div>

              <div className="audit-panel">
                <div className="audit-panel-header">
                  <div>
                    <span className="panel-label">SECURITY ACTIVITY</span>
                    <h4>Recent audit events</h4>
                  </div>
                  <span className="audit-live-badge"><i></i> LIVE MONGODB</span>
                </div>

                {auditLoading ? (
                  <div className="empty-state"><Loader2 className="spin" size={22} /><h4>Loading audit trail</h4><p>Fetching recent security events.</p></div>
                ) : filteredAuditLogs.length === 0 ? (
                  <div className="empty-state"><Shield size={24} /><h4>No audit events found</h4><p>Try another filter or perform a login/screening action.</p></div>
                ) : (
                  <div className="audit-table-wrap">
                    <div className="audit-table audit-table-head">
                      <span>EVENT</span><span>OFFICER</span><span>CASE / RESULT</span><span>TIMESTAMP</span>
                    </div>
                    {filteredAuditLogs.map((log, index) => {
                      const event = log?.event || "UNKNOWN";
                      const details = log?.details || {};
                      const officerName = log?.officer?.name || log?.officer?.username || (event === "LOGIN_FAILED" ? "Unknown officer" : "System");
                      const username = log?.officer?.username || "";
                      const timestamp = log?.timestamp ? new Date(log.timestamp) : null;
                      const eventClass = event.toLowerCase().replaceAll("_", "-");
                      let result = details?.screening_status || details?.risk_score !== undefined ? `${details?.screening_status || "Risk"}${details?.risk_score !== undefined ? ` • ${details.risk_score}/100` : ""}` : event === "LOGIN_FAILED" ? "Access denied" : event === "LOGIN_SUCCESS" ? "Access granted" : event === "LOGOUT" ? "Session ended" : "Recorded";
                      return (
                        <div className="audit-table audit-table-row" key={`${event}-${log?.timestamp || index}-${index}`}>
                          <div className="audit-event-cell">
                            <span className={`audit-event-icon ${eventClass}`}>
                              {event === "SCREENING_COMPLETED" ? <ScanSearch size={15} /> : event === "LOGIN_SUCCESS" ? <LogIn size={15} /> : event === "LOGIN_FAILED" ? <UserX size={15} /> : event === "LOGOUT" ? <LogOut size={15} /> : <Shield size={15} />}
                            </span>
                            <div><strong>{event.replaceAll("_", " ")}</strong><small>{details?.document_type || "Security event"}</small></div>
                          </div>
                          <div className="audit-officer-cell"><strong>{officerName}</strong><small>{username || log?.officer?.designation || "—"}</small></div>
                          <div className="audit-result-cell"><strong>{log?.case_id || "—"}</strong><small>{result}</small></div>
                          <div className="audit-time-cell">{timestamp && !Number.isNaN(timestamp.getTime()) ? timestamp.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—"}</div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </>
          )}

          {/* =================================================
              SETTINGS
          ================================================= */}

          {currentPage === "settings" && (

            <>
              <PageHeader
                eyebrow="SYSTEM SETTINGS"
                title="Settings"
                description="Manage your officer profile, interface preference and secure session."
              />

              <div className="settings-grid">

                <div className="settings-panel settings-profile-panel">
                  <div className="settings-panel-header">
                    <div className="settings-panel-icon">
                      <ShieldCheck size={19} />
                    </div>
                    <div>
                      <span className="panel-label">OFFICER PROFILE</span>
                      <h4>Authorized officer</h4>
                    </div>
                  </div>

                  <div className="settings-profile">
                    <div className="settings-avatar">
                      {(officer?.name || officer?.username || "SO")
                        .split(" ")
                        .map((part) => part[0])
                        .join("")
                        .slice(0, 2)
                        .toUpperCase()}
                    </div>

                    <div className="settings-profile-main">
                      <strong>{officer?.name || "Security Officer"}</strong>
                      <span>{officer?.designation || "Authorized Officer"}</span>
                    </div>

                    <span className="settings-active-badge">
                      <i></i>
                      Active
                    </span>
                  </div>

                  <div className="settings-detail-grid">
                    <div className="settings-detail">
                      <span>OFFICER ID</span>
                      <strong>{officer?.officer_id || "—"}</strong>
                    </div>
                    <div className="settings-detail">
                      <span>USERNAME</span>
                      <strong>{officer?.username || "—"}</strong>
                    </div>
                    <div className="settings-detail">
                      <span>DESIGNATION</span>
                      <strong>{officer?.designation || "—"}</strong>
                    </div>
                    <div className="settings-detail">
                      <span>ACCOUNT STATUS</span>
                      <strong>Authorized</strong>
                    </div>
                  </div>
                </div>

                <div className="settings-panel">
                  <div className="settings-panel-header">
                    <div className="settings-panel-icon">
                      {theme === "dark" ? <Moon size={18} /> : <Sun size={18} />}
                    </div>
                    <div>
                      <span className="panel-label">APPEARANCE</span>
                      <h4>Interface theme</h4>
                    </div>
                  </div>

                  <div className="settings-theme-row">
                    <div>
                      <strong>{theme === "dark" ? "Dark mode" : "Light mode"}</strong>
                      <span>
                        Change the visual theme without changing the screening workspace layout.
                      </span>
                    </div>

                    <button
                      type="button"
                      className="settings-theme-switch"
                      onClick={toggleTheme}
                      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
                    >
                      <span className={theme === "light" ? "active" : ""}>
                        <Sun size={14} />
                        Light
                      </span>
                      <span className={theme === "dark" ? "active" : ""}>
                        <Moon size={14} />
                        Dark
                      </span>
                    </button>
                  </div>
                </div>

                <div className="settings-panel">
                  <div className="settings-panel-header">
                    <div className="settings-panel-icon">
                      <ShieldCheck size={19} />
                    </div>
                    <div>
                      <span className="panel-label">SECURITY</span>
                      <h4>Secure session</h4>
                    </div>
                  </div>

                  <div className="settings-status-list">
                    <div className="settings-status-row">
                      <div>
                        <strong>Authentication</strong>
                        <span>Officer session verified by the screening server.</span>
                      </div>
                      <b className="settings-status-ok">VERIFIED</b>
                    </div>

                    <div className="settings-status-row">
                      <div>
                        <strong>Session</strong>
                        <span>Current authorized session is active.</span>
                      </div>
                      <b className="settings-status-ok">ACTIVE</b>
                    </div>

                    <div className="settings-status-row">
                      <div>
                        <strong>Credential storage</strong>
                        <span>Officer password is not displayed in the console.</span>
                      </div>
                      <b className="settings-status-neutral">PROTECTED</b>
                    </div>
                  </div>

                  <button
                    type="button"
                    className="settings-signout"
                    onClick={handleLogout}
                  >
                    Sign out of VERIGUARD
                  </button>
                </div>

                <div className="settings-panel">
                  <div className="settings-panel-header">
                    <div className="settings-panel-icon">
                      <Activity size={19} />
                    </div>
                    <div>
                      <span className="panel-label">SYSTEM</span>
                      <h4>Service status</h4>
                    </div>
                  </div>

                  <div className="settings-status-list">
                    <div className="settings-status-row compact">
                      <div>
                        <strong>FastAPI screening backend</strong>
                        <span>Document analysis and protected API services.</span>
                      </div>
                      <b className="settings-status-ok">ONLINE</b>
                    </div>

                    <div className="settings-status-row compact">
                      <div>
                        <strong>MongoDB</strong>
                        <span>Screening history and reference data storage.</span>
                      </div>
                      <b className={historyError ? "settings-status-warn" : "settings-status-ok"}>
                        {historyError ? "CHECK" : "CONNECTED"}
                      </b>
                    </div>

                    <div className="settings-status-row compact">
                      <div>
                        <strong>Screening engines</strong>
                        <span>OCR, validation, integrity and face verification pipeline.</span>
                      </div>
                      <b className="settings-status-ok">READY</b>
                    </div>
                  </div>
                </div>

              </div>
            </>
          )}


          {/* =================================================
              REPORTS
          ================================================= */}

          {currentPage === "reports" && (

            <>
              <PageHeader
                eyebrow="REPORTING"
                title="Screening reports"
                description="Generate export-ready reports from live MongoDB screening records."
              />

              <div className="report-panel">
                <div className="report-icon">
                  <FileText size={26} />
                </div>

                <h3>MongoDB screening activity report</h3>
                <p>Live records from the VERIGUARD screening database.</p>

                <div className="report-summary">
                  <div><span>Total Cases</span><strong>{reportData?.summary?.total ?? 0}</strong></div>
                  <div><span>Verified</span><strong>{reportData?.summary?.verified ?? 0}</strong></div>
                  <div><span>Review</span><strong>{reportData?.summary?.review ?? 0}</strong></div>
                  <div><span>High Risk</span><strong>{reportData?.summary?.high_risk ?? 0}</strong></div>
                </div>

                <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", marginTop: "18px" }}>
                  <select value={reportStatusFilter} onChange={(e) => setReportStatusFilter(e.target.value)}>
                    <option value="ALL">All Statuses</option>
                    <option value="VERIFIED">Verified</option>
                    <option value="REVIEW">Review</option>
                    <option value="HIGH RISK">High Risk</option>
                  </select>

                  <select value={reportTypeFilter} onChange={(e) => setReportTypeFilter(e.target.value)}>
                    <option value="ALL">All Document Types</option>
                    {Object.keys(analyticsData?.document_types || {}).map((type) => (
                      <option key={type} value={type}>{type}</option>
                    ))}
                  </select>

                  <button className="secondary-button" onClick={loadReports} disabled={reportLoading}>
                    {reportLoading ? <Loader2 size={16} className="spin" /> : <RotateCcw size={16} />}
                    Refresh
                  </button>
                  <button className="primary-button" onClick={exportReportCSV} disabled={reportLoading || !(reportData?.reports?.length)}>
                    <FileText size={16} /> CSV Export
                  </button>
                  <button className="secondary-button" onClick={exportReportJSON} disabled={reportLoading || !(reportData?.reports?.length)}>
                    <Database size={16} /> JSON Export
                  </button>
                  <button className="secondary-button" onClick={() => window.print()} disabled={reportLoading || !(reportData?.reports?.length)}>
                    <FileText size={16} /> Print / PDF
                  </button>
                </div>

                {reportError && <div className="error-box" style={{ marginTop: "16px" }}>{reportError}</div>}

                {reportLoading ? (
                  <div className="empty-state" style={{ marginTop: "20px" }}><Loader2 className="spin" /> Loading report...</div>
                ) : (
                  <div style={{ overflowX: "auto", marginTop: "20px" }}>
                    <table className="history-table">
                      <thead>
                        <tr>
                          <th>Case ID</th><th>Date</th><th>Document</th><th>Name</th><th>ID</th><th>Status</th><th>Risk</th><th>Reference</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(reportData?.reports || []).map((record, index) => (
                          <tr key={record.case_id || index}>
                            <td>{record.case_id || "—"}</td>
                            <td>{record.screened_at ? new Date(record.screened_at).toLocaleString() : "—"}</td>
                            <td>{record.document_type || "—"}</td>
                            <td>{record.name || "—"}</td>
                            <td>{record.id_number || "—"}</td>
                            <td>{record.screening_status || "—"}</td>
                            <td>{record.risk_assessment?.score ?? 0}/100</td>
                            <td>{record.reference_verification?.status || "NOT_CHECKED"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!(reportData?.reports || []).length && (
                      <div className="empty-state">No screening records match the selected filters.</div>
                    )}
                  </div>
                )}
              </div>
            </>
          )}

          {/* =================================================
              HISTORY CASE DETAILS
          ================================================= */}

          {selectedHistoryRecord && (
            <div
              onClick={() => setSelectedHistoryRecord(null)}
              style={{
                position: "fixed",
                inset: 0,
                background: "rgba(0, 0, 0, 0.72)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 1000,
                padding: "24px",
              }}
            >
              <div
                onClick={(event) => event.stopPropagation()}
                style={{
                  width: "min(900px, 95vw)",
                  maxHeight: "88vh",
                  overflowY: "auto",
                  background: "#08131c",
                  border: "1px solid rgba(120, 180, 210, 0.22)",
                  borderRadius: "16px",
                  padding: "24px",
                  boxShadow: "0 24px 80px rgba(0,0,0,0.5)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    gap: "16px",
                    marginBottom: "22px",
                  }}
                >
                  <div>
                    <span className="panel-label">CASE DETAILS</span>
                    <h3 style={{ margin: "6px 0 4px" }}>
                      {selectedHistoryRecord.caseId}
                    </h3>
                    <p style={{ margin: 0, opacity: 0.7 }}>
                      {selectedHistoryRecord.filename || "Screening case"}
                    </p>
                  </div>

                  <button
                    className="remove-file"
                    onClick={() => setSelectedHistoryRecord(null)}
                    aria-label="Close details"
                  >
                    <X size={18} />
                  </button>
                </div>

                <div className="result-summary">
                  <ResultItem
                    label="DOCUMENT TYPE"
                    value={selectedHistoryRecord.documentType}
                  />
                  <ResultItem
                    label="FULL NAME"
                    value={selectedHistoryRecord.name || "Not detected"}
                  />
                  <ResultItem
                    label="DATE OF BIRTH"
                    value={selectedHistoryRecord.dob || "Not detected"}
                  />
                  <ResultItem
                    label="DOCUMENT ID"
                    value={selectedHistoryRecord.idNumber || "Not detected"}
                  />
                  <ResultItem
                    label="VALIDITY"
                    value={
                      selectedHistoryRecord.validity ||
                      "Not detected"
                    }
                  />
                  <ResultItem
                    label="SCREENING STATUS"
                    value={selectedHistoryRecord.status}
                  />
                </div>

                <div className="risk-assessment-card">
                  <div className="risk-assessment-header">
                    <div>
                      <span className="panel-label">
                        RISK ASSESSMENT
                      </span>
                      <h4>Screening risk</h4>
                    </div>
                  </div>

                  <div className="risk-main">
                    <div className="risk-score-area">
                      <span className="risk-score-label">
                        RISK SCORE
                      </span>
                      <div className="risk-score">
                        <strong>
                          {selectedHistoryRecord.riskScore}
                        </strong>
                        <span>/ 100</span>
                      </div>
                      <span className="risk-confidence">
                        Confidence: {selectedHistoryRecord.confidence}
                      </span>
                    </div>

                    <div className="risk-status-area">
                      <div
                        className={`risk-status-badge ${getRiskClass(
                          selectedHistoryRecord.riskScore
                        )}`}
                      >
                        {selectedHistoryRecord.riskScore >= 60 ? (
                          <ShieldAlert size={17} />
                        ) : selectedHistoryRecord.riskScore >= 35 ? (
                          <AlertTriangle size={17} />
                        ) : (
                          <ShieldCheck size={17} />
                        )}
                        <span>{selectedHistoryRecord.status}</span>
                      </div>
                    </div>
                  </div>
                </div>

                {selectedHistoryRecord.referenceVerification && (
                  <div className="component-panel">
                    <span className="panel-label">
                      REFERENCE DATABASE
                    </span>
                    <h4>Reference verification</h4>

                    <div className="result-summary">
                      <ResultItem
                        label="STATUS"
                        value={
                          selectedHistoryRecord.referenceVerification.status ||
                          "NOT CHECKED"
                        }
                      />
                      <ResultItem
                        label="MATCH %"
                        value={
                          selectedHistoryRecord.referenceVerification
                            .match_percentage !== undefined
                            ? `${selectedHistoryRecord.referenceVerification.match_percentage}%`
                            : "0%"
                        }
                      />
                      <ResultItem
                        label="REFERENCE FOUND"
                        value={
                          selectedHistoryRecord.referenceVerification
                            .reference_found
                            ? "YES"
                            : "NO"
                        }
                      />
                    </div>

                    {Array.isArray(
                      selectedHistoryRecord.referenceVerification
                        .matched_fields
                    ) &&
                      selectedHistoryRecord.referenceVerification
                        .matched_fields.length > 0 && (
                        <div className="findings-list">
                          {selectedHistoryRecord.referenceVerification.matched_fields.map(
                            (field, index) => (
                              <div className="finding" key={index}>
                                <CheckCircle2 size={15} />
                                <span>Matched: {field}</span>
                              </div>
                            )
                          )}
                        </div>
                      )}

                    {Array.isArray(
                      selectedHistoryRecord.referenceVerification
                        .mismatched_fields
                    ) &&
                      selectedHistoryRecord.referenceVerification
                        .mismatched_fields.length > 0 && (
                        <div className="findings-list">
                          {selectedHistoryRecord.referenceVerification.mismatched_fields.map(
                            (field, index) => (
                              <div className="finding" key={index}>
                                <ShieldAlert size={15} />
                                <span>
                                  {field.field}: uploaded "{field.uploaded}" vs
                                  reference "{field.reference}"
                                </span>
                              </div>
                            )
                          )}
                        </div>
                      )}
                  </div>
                )}

                {selectedHistoryRecord.validation && (
                  <div className="component-panel">
                    <span className="panel-label">
                      DOCUMENT VALIDATION
                    </span>
                    <h4>Validation result</h4>
                    <div className="result-summary">
                      <ResultItem
                        label="STATUS"
                        value={
                          selectedHistoryRecord.validation.status ||
                          "UNKNOWN"
                        }
                      />
                      <ResultItem
                        label="REASON"
                        value={
                          selectedHistoryRecord.validation.reason ||
                          "No reason provided"
                        }
                      />
                    </div>
                  </div>
                )}

                <div className="component-panel">
                  <span className="panel-label">
                    DATABASE RECORD
                  </span>
                  <h4>Stored screening information</h4>
                  <div className="ocr-text">
                    Screened on: {selectedHistoryRecord.date} at{" "}
                    {selectedHistoryRecord.time}
                    <br />
                    File: {selectedHistoryRecord.filename || "Not available"}
                  </div>
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "flex-end",
                    marginTop: "18px",
                  }}
                >
                  <button
                    className="secondary-button"
                    onClick={() => setSelectedHistoryRecord(null)}
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
          )}

        </section>

      </main>

    </div>
  );
}


/* =========================================================
   SMALL COMPONENTS
========================================================= */

function Service({
  name,
  description,
  status,
  standby = false,
}) {

  return (

    <div className="service-row">

      <div>

        <strong>
          {name}
        </strong>

        <span>
          {description}
        </span>

      </div>


      <span
        className={`service-status ${
          standby ? "standby" : ""
        }`}
      >

        <i></i>

        {status}

      </span>

    </div>

  );
}


function Pipeline({
  number,
  title,
  description,
}) {

  return (

    <div className="pipeline-item">

      <div className="pipeline-number">
        {number}
      </div>

      <div>

        <strong>
          {title}
        </strong>

        <span>
          {description}
        </span>

      </div>

    </div>

  );
}


function ResultItem({
  label,
  value,
}) {

  return (

    <div className="result-item">

      <span>
        {label}
      </span>

      <strong>
        {value}
      </strong>

    </div>

  );
}


function ComponentCard({
  title,
  value,
  icon,
  good = false,
}) {

  return (

    <div className="component-card">

      <div className="component-card-top">

        <span>
          {title}
        </span>

        {good ? (
          <CheckCircle2 size={15} />
        ) : (
          icon
        )}

      </div>

      <strong>
        {value}
      </strong>

    </div>

  );
}


function PageHeader({
  eyebrow,
  title,
  description,
}) {

  return (

    <div className="welcome">

      <div>

        <p className="eyebrow">
          {eyebrow}
        </p>

        <h3>
          {title}
        </h3>

        <p>
          {description}
        </p>

      </div>

    </div>

  );
}


function RiskBar({
  label,
  count,
  total,
}) {

  const percentage =
    total > 0
      ? Math.round((count / total) * 100)
      : 0;

  return (

    <div className="risk-bar-row">

      <div className="risk-bar-label">

        <span>
          {label}
        </span>

        <strong>
          {count} ({percentage}%)
        </strong>

      </div>


      <div className="risk-bar-track">

        <div
          className="risk-bar-fill"
          style={{
            width: `${percentage}%`,
          }}
        />

      </div>

    </div>

  );
}


export default App;