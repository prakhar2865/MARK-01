import { useEffect, useMemo, useState } from "react";

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
  if (score >= 60) {
    return "HIGH RISK";
  }

  if (score >= 35) {
    return "REVIEW";
  }

  return "VERIFIED";
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
   APP
========================================================= */

function App() {

  const [currentPage, setCurrentPage] =
    useState("dashboard");

  const [selectedFile, setSelectedFile] =
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


  /* =======================================================
     LOAD HISTORY FROM MONGODB THROUGH FASTAPI
  ======================================================= */

  const loadBackendHistory = async () => {
    setHistoryLoading(true);
    setHistoryError("");

    try {
      const response = await fetch(`${API_BASE_URL}/history`);

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
    loadBackendHistory();
  }, []);

  /* =======================================================
     LOAD LIVE ANALYTICS FROM MONGODB THROUGH FASTAPI
  ======================================================= */

  const loadAnalytics = async () => {
    setAnalyticsLoading(true);
    setAnalyticsError("");

    try {
      const response = await fetch(`${API_BASE_URL}/analytics`);

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

      const response = await fetch(`${API_BASE_URL}/reports?${params.toString()}`);

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
    };
  }, [previewUrl]);


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


  /* =======================================================
     REMOVE FILE
  ======================================================= */

  const handleRemoveFile = () => {
    setSelectedFile(null);
    setPreviewUrl(null);
    setAnalysisResult(null);
    setAnalysisError("");
  };


  /* =======================================================
     NEW SCREENING
  ======================================================= */

  const handleNewScreening = () => {
    setSelectedFile(null);
    setPreviewUrl(null);
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

    try {

      const response = await fetch(
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

          <button className="nav-item">
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


            <div className="profile">

              <div className="profile-avatar">
                SO
              </div>

              <div className="profile-info">
                <strong>
                  Security Officer
                </strong>

                <span>
                  Screening Desk
                </span>
              </div>

              <ChevronDown size={16} />

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
                      status="Standby"
                      standby
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


                      <button
                        className="analyze-button"
                        onClick={handleAnalyze}
                        disabled={isAnalyzing}
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
                            {tamperingScore}
                          </strong>

                          <span>
                            / 100
                          </span>

                        </div>

                        <span className="risk-confidence">
                          Confidence: {tamperingConfidence}
                        </span>

                      </div>


                      <div className="risk-status-area">

                        <div
                          className={`risk-status-badge ${getRiskClass(
                            tamperingScore
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
                            {getRiskStatus(
                              tamperingScore
                            )}
                          </span>

                        </div>


                        <p>

                          {tamperingScore >= 60
                            ? "Multiple integrity signals require immediate officer review."
                            : tamperingScore >= 35
                            ? "Some integrity signals require additional verification."
                            : "Current integrity signals indicate a low-priority screening case."}

                        </p>

                      </div>

                    </div>


                    <div className="risk-meter">

                      <div className="risk-meter-track">

                        <div
                          className={`risk-meter-fill ${getRiskClass(
                            tamperingScore
                          )}`}
                          style={{
                            width: `${Math.min(
                              tamperingScore,
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