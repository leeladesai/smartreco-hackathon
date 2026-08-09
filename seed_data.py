import os

from sqlalchemy import select

from app.config import Settings
from app.db import build_session_factory
from app.models import Model, User
from app.security import hash_password
from app.vector import ModelVectorStore, build_embedding_function


SEED_MODELS = [
    {
        "title": "GPT-4o mini",
        "description": (
            "A fast, cost-aware general model for classification, extraction, "
            "and everyday product features."
        ),
        "provider": "OpenAI",
        "modality": "LLM",
        "price": "$0.15 / 1M input tokens",
        "latency_ms": 820,
        "context_window": "128K",
        "use_case_tags": ["structured output", "classification", "cost sensitive"],
        "source_url": "https://platform.openai.com/docs/models",
        "story": (
            "Reach for this when the task is well-defined and volume is high — it wins on "
            "cost-per-call, not raw reasoning depth. Trades some nuance for speed and price "
            "versus a flagship model."
        ),
    },
    {
        "title": "Claude 3.5 Sonnet",
        "description": (
            "Anthropic's balanced flagship — strong reasoning and long-document "
            "work at a lower cost than top-tier frontier models."
        ),
        "provider": "Anthropic",
        "modality": "LLM",
        "price": "$3.00 / 1M input tokens",
        "latency_ms": 640,
        "context_window": "200K",
        "use_case_tags": ["long context", "reasoning", "document analysis"],
        "source_url": "https://www.anthropic.com/pricing",
        "story": (
            "Pick this over a cheaper model once the task needs multi-step reasoning or the "
            "input document won't fit a smaller context window — the cost premium buys "
            "fewer follow-up corrections."
        ),
    },
    {
        "title": "ElevenLabs Turbo v2.5",
        "description": (
            "Low-latency text-to-speech for conversational agents that need "
            "streaming audio quickly."
        ),
        "provider": "ElevenLabs",
        "modality": "Voice",
        "price": "$0.0002 / character",
        "latency_ms": 275,
        "context_window": "5,000 characters",
        "use_case_tags": ["real-time voice", "customer support", "streaming"],
        "source_url": "https://elevenlabs.io/docs",
        "story": (
            "Good default for customer-facing voice agents where voice quality matters as "
            "much as speed — beats Cartesia Sonic on naturalness, loses to it on raw latency."
        ),
    },
    {
        "title": "Cartesia Sonic",
        "description": (
            "Ultra-low-latency speech generation built for real-time voice agents "
            "where every millisecond of round trip matters."
        ),
        "provider": "Cartesia",
        "modality": "Voice",
        "price": "$0.00015 / character",
        "latency_ms": 135,
        "context_window": "N/A",
        "use_case_tags": ["real-time voice", "low latency", "voice agents"],
        "source_url": "https://cartesia.ai",
        "story": (
            "Choose this when latency is the deciding constraint — e.g. live phone-call "
            "agents where any pause reads as a dropped connection. Trades some voice "
            "naturalness for the fastest round trip in this catalog."
        ),
    },
    {
        "title": "Flux.1 Pro",
        "description": (
            "High-fidelity image generation for product concepts, marketing "
            "assets, and visual exploration."
        ),
        "provider": "Black Forest Labs",
        "modality": "Image",
        "price": "$0.05 / image",
        "context_window": "2,048px",
        "use_case_tags": ["image generation", "concept art", "marketing"],
        "source_url": "https://bfl.ai/models",
        "story": (
            "The pick when output quality is customer-facing — marketing assets, hero "
            "images — and the per-image cost is a rounding error next to the design time "
            "it saves."
        ),
    },
    {
        "title": "Stable Diffusion 3.5",
        "description": (
            "Open-weight image generation with strong prompt adherence at a "
            "fraction of the cost of closed-source alternatives."
        ),
        "provider": "Stability AI",
        "modality": "Image",
        "price": "$0.035 / image",
        "context_window": "1,536px",
        "use_case_tags": ["image generation", "open weights", "cost sensitive"],
        "source_url": "https://stability.ai/news/stable-diffusion-3-5",
        "story": (
            "Reach for this over Flux.1 Pro when volume is high or self-hosting matters — "
            "open weights mean no per-call lock-in, at a modest quality step down."
        ),
    },
    {
        "title": "Runway Gen-3",
        "description": (
            "Text-to-video generation for short-form clips, concept previews, "
            "and storyboard exploration."
        ),
        "provider": "Runway",
        "modality": "Video",
        "price": "$0.10 / second",
        "context_window": "10s max",
        "use_case_tags": ["video generation", "storyboarding", "concept preview"],
        "source_url": "https://runwayml.com/research/introducing-gen-3-alpha",
        "story": (
            "The only video option in this catalog — use it for early-stage concept "
            "previews rather than final-cut footage, given the 10s clip ceiling."
        ),
    },
    {
        "title": "Voyage-3",
        "description": (
            "Embedding model for semantic retrieval across technical documents "
            "and product catalogs."
        ),
        "provider": "Voyage AI",
        "modality": "Embedding",
        "price": "$0.02 / 1M tokens",
        "context_window": "32K",
        "use_case_tags": ["semantic search", "retrieval", "reranking"],
        "source_url": "https://docs.voyageai.com/docs/embeddings",
        "story": (
            "Default choice for a new RAG pipeline over technical/product docs — tuned "
            "specifically for that domain rather than being a general-purpose embedding."
        ),
    },
    {
        "title": "Cohere Embed v3",
        "description": (
            "Multilingual embedding model tuned for retrieval-augmented generation "
            "and search re-ranking."
        ),
        "provider": "Cohere",
        "modality": "Embedding",
        "price": "$0.10 / 1M tokens",
        "context_window": "512",
        "use_case_tags": ["semantic search", "multilingual", "reranking"],
        "source_url": "https://cohere.com/pricing",
        "story": (
            "Switch to this over Voyage-3 once the corpus is multilingual — that's the one "
            "axis it's purpose-built for; single-language English retrieval doesn't need it."
        ),
    },
    {
        "title": "NebulaSynth LLM X1",
        "description": (
            "A large language model optimized for complex reasoning and "
            "creative writing tasks."
        ),
        "provider": "StellarMind Tech",
        "modality": "LLM",
        "price": "$0.12 / 1M tokens",
        "latency_ms": 250,
        "context_window": "50,000 tokens",
        "use_case_tags": ["creative writing", "reasoning", "content generation"],
        "source_url": "https://docs.stellarmindtech.com/nebulasynth-x1",
    },
    {
        "title": "VocalAura Voicewave 3000",
        "description": (
            "An advanced speech synthesis engine perfect for immersive "
            "narration and voice assistants."
        ),
        "provider": "EchoForge Systems",
        "modality": "Voice",
        "price": "$0.08 / second",
        "latency_ms": 100,
        "use_case_tags": ["speech synthesis", "virtual assistants", "audio narration"],
        "source_url": "https://docs.echoforgesys.com/voicewave3000",
    },
    {
        "title": "PixoraVision X",
        "description": (
            "High-fidelity image generation model suitable for creative and "
            "commercial visual content."
        ),
        "provider": "Imagino Labs",
        "modality": "Image",
        "price": "$0.05 / image",
        "latency_ms": 320,
        "use_case_tags": ["art creation", "advertisement", "concept design"],
        "source_url": "https://docs.imagino.ai/pixoravision-x",
    },
    {
        "title": "TuneMeld VideoPro",
        "description": (
            "Next-gen AI for rapid video synthesis and editing, ideal for "
            "marketing and entertainment."
        ),
        "provider": "Cineform Dynamics",
        "modality": "Video",
        "price": "$0.20 / minute",
        "latency_ms": 500,
        "context_window": "10 seconds max",
        "use_case_tags": ["video editing", "ad creation", "visual effects"],
        "source_url": "https://docs.cineformdynamics.com/tunemeld-videopro",
    },
    {
        "title": "CerebraEmbed v4",
        "description": (
            "Powerful embedding model for semantic search, clustering, and "
            "recommendation systems."
        ),
        "provider": "NeuroNest AI",
        "modality": "Embedding",
        "price": "$0.0002 / 1K embeddings",
        "use_case_tags": ["semantic search", "recommendation", "clustering"],
        "source_url": "https://docs.neuronest.ai/cerebraembed-v4",
    },
    {
        "title": "HoloBlend Multimodal 2.3",
        "description": (
            "A versatile model capable of integrating text, image, and "
            "audio for comprehensive multimedia tasks."
        ),
        "provider": "PolyData Labs",
        "modality": "Multimodal",
        "price": "$0.25 / 1K multimodal units",
        "latency_ms": 400,
        "context_window": "64K",
        "use_case_tags": ["multimedia synthesis", "context understanding"],
        "source_url": "https://docs.polydatalabs.com/holoblend-2.3",
    },
    {
        "title": "NebulaSynth LLM Z9",
        "description": (
            "A smaller, efficient language model tailored for embedded "
            "applications and edge devices."
        ),
        "provider": "StellarMind Tech",
        "modality": "LLM",
        "price": "$0.07 / 1M tokens",
        "latency_ms": 180,
        "context_window": "8,000 tokens",
        "use_case_tags": ["edge AI", "embedded systems", "lightweight reasoning"],
        "source_url": "https://docs.stellarmindtech.com/nebulasynth-z9",
    },
    {
        "title": "SonoraVoice FX",
        "description": (
            "Realistic voice conversion and modulation tools for "
            "entertainment and accessibility."
        ),
        "provider": "VocalVortex Inc.",
        "modality": "Voice",
        "price": "$0.06 / second",
        "latency_ms": 120,
        "use_case_tags": ["voice conversion", "accessibility", "sound design"],
        "source_url": "https://docs.vocalvortex.com/sonoravoice-fx",
    },
    {
        "title": "ClaraRender AI",
        "description": (
            "Photorealistic image rendering model perfect for product "
            "visualization and digital art."
        ),
        "provider": "RenderTech AI",
        "modality": "Image",
        "price": "$0.08 / image",
        "latency_ms": 350,
        "use_case_tags": ["digital art", "product design", "visualization"],
        "source_url": "https://docs.rendertechai.com/clararender",
    },
    {
        "title": "VidoraStream 4K",
        "description": (
            "High-quality AI-driven video generation for cinematic and "
            "streaming applications."
        ),
        "provider": "StreamForge Networks",
        "modality": "Video",
        "price": "$0.25 / minute",
        "latency_ms": 600,
        "context_window": "15s max",
        "use_case_tags": ["cinema", "streaming", "advertisement"],
        "source_url": "https://docs.streamforgenetworks.com/vidorastream-4k",
    },
    {
        "title": "EchoEmbed v5",
        "description": (
            "State-of-the-art embedding model optimized for fast search and "
            "clustering routines."
        ),
        "provider": "NeuroNest AI",
        "modality": "Embedding",
        "price": "$0.0002 / 1K embeddings",
        "use_case_tags": ["search", "clustering", "recommendation"],
        "source_url": "https://docs.neuronest.ai/echoembed-v5",
    },
    {
        "title": "PolyMosaic Multimodal 1.8",
        "description": (
            "A comprehensive model integrating text, images, and speech for "
            "rich content creation."
        ),
        "provider": "PolyData Labs",
        "modality": "Multimodal",
        "price": "$0.30 / 1K multimodal units",
        "latency_ms": 420,
        "context_window": "100K",
        "use_case_tags": ["multimedia creation", "context blending"],
        "source_url": "https://docs.polydatalabs.com/polymosaic-1.8",
    },
    {
        "title": "MindScribe LLM Compact",
        "description": (
            "An efficient language model tailored for mobile and low-power "
            "devices, ideal for note-taking and summarization."
        ),
        "provider": "LiteLogic AI",
        "modality": "LLM",
        "price": "$0.05 / 1M tokens",
        "latency_ms": 200,
        "context_window": "4,000 tokens",
        "use_case_tags": ["note-taking", "summarization", "mobile AI"],
        "source_url": "https://docs.litelogic.ai/mindscrib-compact",
    },
    {
        "title": "VoxCraft AudioSynth",
        "description": (
            "AI audio generation tailored for game sound design, podcasts, "
            "and background scores."
        ),
        "provider": "AudioNexus Ltd.",
        "modality": "Voice",
        "price": "$0.09 / second",
        "latency_ms": 110,
        "use_case_tags": ["game audio", "podcasts", "sound design"],
        "source_url": "https://docs.audionexus.com/voxcraft-aisynth",
    },
    {
        "title": "RenderSphere AI",
        "description": (
            "Real-time 3D scene rendering with procedural generation "
            "capabilities, suitable for virtual worlds."
        ),
        "provider": "VirtualVista Inc.",
        "modality": "Image",
        "price": "$0.10 / image",
        "latency_ms": 400,
        "use_case_tags": ["virtual reality", "game development", "simulation"],
        "source_url": "https://docs.virtualvista.com/rendersphere-ai",
    },
    {
        "title": "CynthiaVision Pix",
        "description": (
            "Stylized image generation with a focus on artistic effects for "
            "creative projects."
        ),
        "provider": "Artify AI",
        "modality": "Image",
        "price": "$0.07 / image",
        "latency_ms": 330,
        "use_case_tags": ["artistic effects", "creative design"],
        "source_url": "https://docs.artifyai.com/cynthiavision-pix",
    },
    {
        "title": "ViTale VideoForge",
        "description": (
            "An innovative model for automated video editing, including "
            "scene detection and montage creation."
        ),
        "provider": "EditFlow Labs",
        "modality": "Video",
        "price": "$0.30 / minute",
        "latency_ms": 550,
        "context_window": "20 seconds max",
        "use_case_tags": ["video editing", "automatic montage"],
        "source_url": "https://docs.editflowlabs.com/vitale-videoforge",
    },
    {
        "title": "AstraMind TextSynth",
        "description": (
            "Optimized for high-quality natural language understanding and "
            "generation tasks with extensive context support."
        ),
        "provider": "NebulaCore AI",
        "modality": "LLM",
        "price": "$0.02 / 1M tokens",
        "latency_ms": 150,
        "context_window": "64K",
        "use_case_tags": ["chatbots", "content creation", "Q&A"],
        "source_url": "https://docs.nebulacore.ai/astramind-textsynth",
    },
    {
        "title": "OrionVox VoiceMaster",
        "description": (
            "Provides realistic speech synthesis and voice conversion for "
            "interactive applications."
        ),
        "provider": "Voxify Labs",
        "modality": "Voice",
        "price": "$0.05 / voice",
        "latency_ms": 50,
        "use_case_tags": ["voice cloning", "interactive voice", "entertainment"],
        "source_url": "https://docs.voxifylabs.com/orionvox",
    },
    {
        "title": "Luminara ImageCraft",
        "description": (
            "Generates high-resolution images from textual prompts, "
            "suitable for creative design workflows."
        ),
        "provider": "Pixora Technologies",
        "modality": "Image",
        "price": "$0.10 / image",
        "latency_ms": 200,
        "use_case_tags": ["art generation", "advertising", "concept design"],
        "source_url": "https://docs.pixoratech.com/luminaracraft",
    },
    {
        "title": "SpectraFlow VideoGen",
        "description": (
            "Transforms textual descriptions into short video clips with "
            "synchronized visuals and audio."
        ),
        "provider": "FlickerSoft",
        "modality": "Video",
        "price": "$0.20 / second",
        "latency_ms": 1000,
        "context_window": "10s max",
        "use_case_tags": ["video creation", "storytelling", "ads"],
        "source_url": "https://docs.flickersoft.com/spectraflow",
    },
    {
        "title": "EmbedPulse SemanticEmbed",
        "description": (
            "Provides vector embeddings for semantic search and clustering "
            "tasks across large datasets."
        ),
        "provider": "CortexWave",
        "modality": "Embedding",
        "price": "$0.0002 / character",
        "latency_ms": 30,
        "use_case_tags": ["search", "recommendation", "clustering"],
        "source_url": "https://docs.cortexwave.com/embeddulse",
    },
    {
        "title": "NovaMultiModal Integrator",
        "description": (
            "A versatile multimodal model combining text, image, and audio "
            "understanding for complex workflows."
        ),
        "provider": "Synthoria AI",
        "modality": "Multimodal",
        "price": "$0.15 / 1M tokens",
        "latency_ms": 250,
        "context_window": "128K",
        "use_case_tags": [
            "multimodal analysis",
            "multimedia moderation",
            "content synthesis",
        ],
        "source_url": "https://docs.synthoria.ai/novamultimodal",
    },
    {
        "title": "VireoVision Insight",
        "description": (
            "Specialized in analyzing video data for object detection, "
            "scene understanding, and event recognition."
        ),
        "provider": "VisioLogic",
        "modality": "Video",
        "price": "$0.15 / second",
        "latency_ms": 120,
        "context_window": "5,000 frames",
        "use_case_tags": ["video analytics", "security", "autonomous systems"],
        "source_url": "https://docs.visiologic.com/vireovision",
    },
    {
        "title": "EchoTone AudioForge",
        "description": (
            "High-fidelity speech synthesis and audio editing capabilities "
            "for media production."
        ),
        "provider": "SonarSoft",
        "modality": "Voice",
        "price": "$0.06 / minute",
        "latency_ms": 40,
        "use_case_tags": ["audio generation", "voiceover", "podcasting"],
        "source_url": "https://docs.sonarsoft.com/echotone",
    },
    {
        "title": "PixelWave RenderX",
        "description": (
            "Advanced image rendering from sketches and prompts, ideal for "
            "digital artists and designers."
        ),
        "provider": "Artify Labs",
        "modality": "Image",
        "price": "$0.12 / image",
        "latency_ms": 220,
        "use_case_tags": ["illustration", "concept art", "visual development"],
        "source_url": "https://docs.artifylabs.com/pixelwave",
    },
    {
        "title": "FlowPix VideoSynth",
        "description": (
            "Enables rapid video prototyping from textual and visual inputs "
            "for creatives."
        ),
        "provider": "DreamMotion",
        "modality": "Video",
        "price": "$0.25 / second",
        "latency_ms": 950,
        "context_window": "8s max",
        "use_case_tags": ["video prototyping", "animation", "storyboarding"],
        "source_url": "https://docs.dreammotion.com/flowpix",
    },
    {
        "title": "NeuroSense Embeddify",
        "description": (
            "Highly optimized embedding model for real-time semantic "
            "similarity and clustering."
        ),
        "provider": "DeepSynapse",
        "modality": "Embedding",
        "price": "$0.0002 / character",
        "latency_ms": 25,
        "use_case_tags": ["search indexing", "recommendation", "clustering"],
        "source_url": "https://docs.deepsynapse.com/neurosense",
    },
    {
        "title": "HoloVision Augment",
        "description": (
            "Multimodal AR enhancement system to overlay generated visuals "
            "and audio into real-world environments."
        ),
        "provider": "Augmentis Inc.",
        "modality": "Multimodal",
        "price": "$0.20 / 1M tokens",
        "context_window": "256K",
        "use_case_tags": ["AR", "interactive media", "entertainment"],
        "source_url": "https://docs.augmentis.com/holovision",
    },
    {
        "title": "VocalMirage AudioSpline",
        "description": (
            "Sophisticated voice synthesis with emotional tone modulation "
            "for characters and narrators."
        ),
        "provider": "SonicWave",
        "modality": "Voice",
        "price": "$0.07 / minute",
        "latency_ms": 35,
        "use_case_tags": ["entertainment", "narration", "voice acting"],
        "source_url": "https://docs.sonicwave.com/vocalmirage",
    },
    {
        "title": "ChromaFrame ImageFlow",
        "description": (
            "Dynamic AI-driven image editing with style transfer and "
            "enhancement options."
        ),
        "provider": "ColorCraft AI",
        "modality": "Image",
        "price": "$0.11 / image",
        "latency_ms": 180,
        "use_case_tags": ["photo editing", "digital art", "visual effects"],
        "source_url": "https://docs.colorcraftai.com/chromaframe",
    },
    {
        "title": "Streamline VideoCaster",
        "description": (
            "Real-time video editing and stylization for live streaming and "
            "content creation."
        ),
        "provider": "LiveEdit Labs",
        "modality": "Video",
        "price": "$0.22 / second",
        "latency_ms": 850,
        "context_window": "12s max",
        "use_case_tags": ["live streaming", "video remixing", "content moderation"],
        "source_url": "https://docs.liveeditlabs.com/streamline",
    },
    {
        "title": "PolySpectra MultimodalFusion",
        "description": (
            "Integrates multiple data modalities to understand complex "
            "multimedia inputs comprehensively."
        ),
        "provider": "FusionCore",
        "modality": "Multimodal",
        "price": "$0.18 / 1M tokens",
        "context_window": "256K",
        "use_case_tags": [
            "multimedia analysis",
            "automated tagging",
            "semantic understanding",
        ],
        "source_url": "https://docs.fusioncore.com/polyspectra",
    },
    {
        "title": "AudioGlow VoiceScape",
        "description": (
            "Generates immersive background sounds and audio effects for "
            "multimedia projects."
        ),
        "provider": "EchoWave",
        "modality": "Voice",
        "price": "$0.04 / second",
        "latency_ms": 45,
        "use_case_tags": ["sound design", "game development", "film production"],
        "source_url": "https://docs.echowave.com/audioglow",
    },
    {
        "title": "VisionEvolve PixInsight",
        "description": (
            "AI-powered image analysis and enhancement to support "
            "scientific and medical imaging tasks."
        ),
        "provider": "Medisynth",
        "modality": "Image",
        "price": "$0.13 / image",
        "latency_ms": 210,
        "use_case_tags": ["medical imaging", "scientific research", "diagnostics"],
        "source_url": "https://docs.medisynth.com/visionevolve",
    },
    {
        "title": "VeriQuantum SpeechCore",
        "description": (
            "Specialized for real-time speech recognition and dialogue "
            "systems, providing high accuracy and low latency responses."
        ),
        "provider": "NeuroVibe Labs",
        "modality": "Voice",
        "price": "$0.04 / second",
        "latency_ms": 150,
        "context_window": "10s max",
        "use_case_tags": ["speech recognition", "dialogue"],
        "source_url": "https://docs.neurovibelabs.com/veriquantum-speechcore",
    },
    {
        "title": "AstraSynth VisionX",
        "description": (
            "Optimized for high-quality image synthesis and artistic "
            "rendering tasks with crisp detail fidelity."
        ),
        "provider": "PhotonForge Inc.",
        "modality": "Image",
        "price": "$0.20 / image",
        "latency_ms": 250,
        "use_case_tags": ["artistic rendering", "creativity"],
        "source_url": "https://docs.photonforge.com/astrasynth-visionx",
    },
    {
        "title": "SkyPulse VideoFlow",
        "description": (
            "Designed for real-time video generation and editing, "
            "supporting dynamic scene creation."
        ),
        "provider": "Streamline Media",
        "modality": "Video",
        "price": "$0.05 / second",
        "latency_ms": 300,
        "context_window": "10s max",
        "use_case_tags": ["video editing", "live streaming"],
        "source_url": "https://docs.streamlinemedia.com/skypulse-videoflow",
    },
    {
        "title": "LumaEmbed VisionNest",
        "description": (
            "Ideal for embedding extraction from images to facilitate "
            "search, classification, and similarity tasks."
        ),
        "provider": "OptiCore Labs",
        "modality": "Embedding",
        "price": "$0.0002 / character",
        "context_window": "5,000 characters",
        "use_case_tags": ["search", "classification"],
        "source_url": "https://docs.opticorelabs.com/lumabase-visionnest",
    },
    {
        "title": "QuantumLink MultimodalX",
        "description": (
            "A versatile model supporting simultaneous processing of text, "
            "images, and audio for complex context understanding."
        ),
        "provider": "SynthWave Technologies",
        "modality": "Multimodal",
        "price": "$0.02 / 1M tokens",
        "latency_ms": 400,
        "context_window": "128K",
        "use_case_tags": ["multimodal understanding", "context integration"],
        "source_url": "https://docs.synthwavetec.com/quantumlink-multimodalex",
    },
    {
        "title": "PyraVoice Express",
        "description": (
            "A fast voice synthesis model optimized for conversational AI "
            "with realistic tone and pitch options."
        ),
        "provider": "VocalForge Solutions",
        "modality": "Voice",
        "price": "$0.03 / second",
        "latency_ms": 100,
        "context_window": "15s max",
        "use_case_tags": ["voice synthesis", "virtual assistants"],
        "source_url": "https://docs.vocalforgesolutions.com/pyravoice-express",
    },
    {
        "title": "ArtemisPix VisualForge",
        "description": (
            "Designed for high-resolution image generation with detailed "
            "textures and complex scenes."
        ),
        "provider": "Imaginuity Creations",
        "modality": "Image",
        "price": "$0.25 / image",
        "latency_ms": 350,
        "use_case_tags": ["concept art", "design"],
        "source_url": "https://docs.imaginuitycreations.com/artemis-pix",
    },
    {
        "title": "VividStream VideoSynth",
        "description": (
            "Enables high-fidelity video synthesis for cinematic and "
            "entertainment applications with real-time capabilities."
        ),
        "provider": "CineVerse Labs",
        "modality": "Video",
        "price": "$0.06 / second",
        "latency_ms": 400,
        "context_window": "10s max",
        "use_case_tags": ["film production", "animation"],
        "source_url": "https://docs.cineverse.com/vividstream-videosynth",
    },
    {
        "title": "PhotonEmbed Embeddify",
        "description": (
            "Offers fast embedding extraction from text and images for use "
            "in search and recommendation systems."
        ),
        "provider": "SyncMind Studios",
        "modality": "Embedding",
        "price": "$0.0003 / character",
        "context_window": "4,000 characters",
        "use_case_tags": ["search", "recommendation"],
        "source_url": "https://docs.syncmindstudios.com/photonembed-embeddify",
    },
    {
        "title": "HexaMulti ModalSense",
        "description": (
            "Supports multi-sensory data processing from text, images, and "
            "audio to facilitate advanced AI understanding."
        ),
        "provider": "FusionCore Innovations",
        "modality": "Multimodal",
        "price": "$0.03 / 1M tokens",
        "latency_ms": 420,
        "context_window": "100K",
        "use_case_tags": ["multi-sensory integration", "scene understanding"],
        "source_url": "https://docs.fusioncoreinnovations.com/hexamultimodal-sense",
    },
    {
        "title": "EchoChamber AudioMorph",
        "description": (
            "Specialized for emotional and musical audio synthesis, "
            "supporting rich tonal variations."
        ),
        "provider": "Resonate Labs",
        "modality": "Voice",
        "price": "$0.08 / minute",
        "latency_ms": 200,
        "use_case_tags": ["music synthesis", "emotional AI"],
        "source_url": "https://docs.resonatelabs.com/echochamber-audiomorph",
    },
    {
        "title": "SpectraFlow VisionWave",
        "description": (
            "A real-time video processing model for surveillance and "
            "analytics with high frame-rate support."
        ),
        "provider": "OmniVision Inc.",
        "modality": "Video",
        "price": "$0.07 / second",
        "latency_ms": 320,
        "context_window": "10s max",
        "use_case_tags": ["surveillance", "analytics"],
        "source_url": "https://docs.omnivision.com/spectrafLow-visionwave",
    },
    {
        "title": "NebulaEmbed SynthiCore",
        "description": (
            "Facilitates embedding generation from large text datasets to "
            "support clustering and semantic search."
        ),
        "provider": "Celestial Dataworks",
        "modality": "Embedding",
        "price": "$0.00015 / character",
        "context_window": "6,000 characters",
        "use_case_tags": ["semantic search", "clustering"],
        "source_url": "https://docs.celestialdataworks.com/nebulaembed-synthicore",
    },
    {
        "title": "Vortex Multimodal Nexus",
        "description": (
            "Enables seamless integration and processing of text, images, "
            "and audio streams for complex tasks."
        ),
        "provider": "HorizonFusion Labs",
        "modality": "Multimodal",
        "price": "$0.025 / 1M tokens",
        "latency_ms": 410,
        "context_window": "150K",
        "use_case_tags": ["cross-modal reasoning", "context fusion"],
        "source_url": "https://docs.horizonfusion.com/vortex-nexus",
    },
    {
        "title": "NovaVibe AudioVision",
        "description": (
            "Synchronizes audio and visual content for immersive multimedia "
            "experiences with low latency."
        ),
        "provider": "EchoSky Studios",
        "modality": "Multimodal",
        "price": "$0.03 / 1M tokens",
        "latency_ms": 330,
        "context_window": "120K",
        "use_case_tags": ["multimedia synchronization", "AR/VR"],
        "source_url": "https://docs.echoskystudios.com/novavibe",
    },
    {
        "title": "LuminaImage RenderX",
        "description": (
            "High-speed rendering model for generating detailed "
            "visualizations and prototypes from sketches."
        ),
        "provider": "BrightFrame Inc.",
        "modality": "Image",
        "price": "$0.22 / image",
        "latency_ms": 370,
        "use_case_tags": ["design prototyping", "visualization"],
        "source_url": "https://docs.brightframeinc.com/luminaimage-renderx",
    },
    {
        "title": "StreamSync VideoMeld",
        "description": (
            "Combines multiple video sources into synchronized, coherent "
            "outputs suitable for live broadcasting."
        ),
        "provider": "StreamSync Solutions",
        "modality": "Video",
        "price": "$0.055 / second",
        "latency_ms": 390,
        "context_window": "10s max",
        "use_case_tags": ["live streaming", "multiview editing"],
        "source_url": "https://docs.streamsyncsolutions.com/streamsynth-videomeld",
    },
    {
        "title": "NeuroVista HydroLite",
        "description": (
            "Specialized for real-time vision processing in embedded "
            "systems, ideal for robotics and autonomous vehicles."
        ),
        "provider": "AstraCore Innovations",
        "modality": "Image",
        "price": "$0.12 / image",
        "latency_ms": 45,
        "context_window": "4,096px",
        "use_case_tags": ["object detection", "image classification"],
        "source_url": "https://docs.astracore.com/neurovista-hydrolite",
    },
    {
        "title": "VividSynth Orbis",
        "description": (
            "Designed for ultra-high-definition video synthesis and editing "
            "applications with low latency."
        ),
        "provider": "OptiWave Labs",
        "modality": "Video",
        "price": "$0.18 / second",
        "latency_ms": 60,
        "context_window": "10s max",
        "use_case_tags": ["video generation", "special effects"],
        "source_url": "https://docs.optiwavelabs.com/vivid-synth-orbis",
    },
    {
        "title": "EchoMind Serenade",
        "description": (
            "A powerful voice synthesis model suitable for creating natural "
            "chatbot interactions and voice assistants."
        ),
        "provider": "VocalForge Inc.",
        "modality": "Voice",
        "price": "$0.07 / character",
        "latency_ms": 80,
        "context_window": "2,048 characters",
        "use_case_tags": ["voice synthesis", "dialog systems"],
        "source_url": "https://docs.vocalforge.com/echomind-serenade",
    },
    {
        "title": "PolySpectra Modular",
        "description": (
            "A versatile multimodal model for combining text, images, and "
            "audio in creative applications."
        ),
        "provider": "Fusionary AI",
        "modality": "Multimodal",
        "price": "$0.07 / 1M tokens",
        "context_window": "128K",
        "use_case_tags": ["content creation", "multimodal research"],
        "source_url": "https://docs.fusionaryai.com/polyspectra-modular",
    },
    {
        "title": "TextSynth Astra",
        "description": (
            "A high-quality language model suited for creative writing, "
            "summarization, and conversational agents."
        ),
        "provider": "LinguaVerse",
        "modality": "LLM",
        "price": "$0.025 / 1K tokens",
        "latency_ms": 150,
        "context_window": "8,192 tokens",
        "use_case_tags": ["text generation", "chatbots"],
        "source_url": "https://docs.linguaverse.com/astsra",
    },
    {
        "title": "VortexVision Ignite",
        "description": (
            "Focused on real-time image processing for security and "
            "surveillance systems with low latency."
        ),
        "provider": "Sentinel Systems",
        "modality": "Image",
        "price": "$0.09 / image",
        "latency_ms": 50,
        "context_window": "5,000px",
        "use_case_tags": ["security", "image analysis"],
        "source_url": "https://docs.sentinelsystems.com/vortexvision-ignite",
    },
    {
        "title": "VivoWave AudioVision",
        "description": (
            "Enables synchronized audio and visual outputs for immersive "
            "multimedia experiences."
        ),
        "provider": "AudioFusion",
        "modality": "Multimodal",
        "price": "$0.15 / interaction",
        "context_window": "Unlimited",
        "use_case_tags": ["multimedia", "interactive content"],
        "source_url": "https://docs.audiofusion.com/vivowave-audiovisual",
    },
    {
        "title": "SkySynth VisionPro",
        "description": (
            "Designed for high-quality image analysis and generation tasks, "
            "ideal for creative workflows and visual data insights."
        ),
        "provider": "CelestialLogic Labs",
        "modality": "Image",
        "price": "$0.03 / image",
        "latency_ms": 200,
        "use_case_tags": ["image classification", "generation", "visual analysis"],
        "source_url": "https://docs.celestiallogic.com/skyshenith-visionpro",
    },
    {
        "title": "AstraFlow Multimodal-X",
        "description": (
            "Excellent for integrating text, image, and video inputs to "
            "support complex multi-modal applications."
        ),
        "provider": "NebulaX Technologies",
        "modality": "Multimodal",
        "price": "$0.06 / combined input",
        "latency_ms": 250,
        "context_window": "128K",
        "use_case_tags": ["multimodal understanding", "creative content", "research"],
        "source_url": "https://docs.nebulaxtech.com/astraflow-multimodalx",
    },
    {
        "title": "NeonMosaic Multimodal 2.8",
        "description": (
            "Integrates text, images, and video seamlessly for "
            "multi-layered storytelling and digital art projects."
        ),
        "provider": "PixelShift Inc",
        "modality": "Multimodal",
        "price": "$0.09 / combined input",
        "latency_ms": 320,
        "context_window": "140K",
        "use_case_tags": ["digital art", "storytelling", "multimodal synthesis"],
        "source_url": "https://docs.pixelshiftinc.com/neonmosaic",
    },
    {
        "title": "NeuroScope VisionX",
        "description": (
            "Specialized for high-fidelity image analysis and "
            "classification tasks with quick turnaround."
        ),
        "provider": "AetherTech Labs",
        "modality": "Image",
        "price": "$0.10 / image",
        "latency_ms": 150,
        "context_window": "2,048px",
        "use_case_tags": ["image recognition", "classification", "object detection"],
        "source_url": "https://docs.aethertechlabs.com/neuroscope-visionx",
    },
    {
        "title": "VortexMultimodal Nexus",
        "description": (
            "A versatile multimodal model optimized for seamless "
            "integration of text, images, and audio inputs."
        ),
        "provider": "Lumina Dynamics",
        "modality": "Multimodal",
        "price": "$0.02 / 1M tokens",
        "latency_ms": 200,
        "context_window": "128K",
        "use_case_tags": [
            "multimodal reasoning",
            "content summarization",
            "multimedia analysis",
        ],
        "source_url": "https://docs.luminadynamics.com/vortexnexus",
    },
    {
        "title": "QuantumVisio VideoSynth",
        "description": (
            "Ideal for fast, high-resolution video content creation and "
            "editing with real-time processing."
        ),
        "provider": "CineCore AI",
        "modality": "Video",
        "price": "$0.15 / second",
        "latency_ms": 250,
        "context_window": "10s max",
        "use_case_tags": ["video synthesis", "content creation", "visual effects"],
        "source_url": "https://docs.cinecoreai.com/quantumvisio-videosynth",
    },
    {
        "title": "NeuroVista CortexFlow",
        "description": (
            "Ideal for advanced neuro-linguistic analysis and contextual "
            "understanding in complex datasets."
        ),
        "provider": "Cognify Labs",
        "modality": "LLM",
        "price": "$0.18 / 1M tokens",
        "latency_ms": 150,
        "context_window": "40K",
        "use_case_tags": ["context comprehension", "storytelling", "summarization"],
        "source_url": "https://docs.cognifylabs.com/neurovista/cortexflow",
    },
    {
        "title": "AstraFlow Spectrum",
        "description": (
            "Designed for seamless multimodal integration across text, "
            "images, and video for enhanced content analysis."
        ),
        "provider": "NovaSynth Inc.",
        "modality": "Multimodal",
        "price": "$0.25 / 1M tokens",
        "latency_ms": 200,
        "context_window": "50K",
        "use_case_tags": ["multimodal inference", "content fusion", "media tagging"],
        "source_url": "https://docs.novasynth.com/astraflow/spectrum",
    },
    {
        "title": "QuantumVisio PixelStream",
        "description": (
            "Specialized in high-resolution image and video processing for "
            "real-time surveillance and inspection tasks."
        ),
        "provider": "Opticore Solutions",
        "modality": "Video",
        "price": "$0.05 / second",
        "latency_ms": 50,
        "use_case_tags": ["video analysis", "object detection", "security"],
        "source_url": "https://docs.opticoresolutions.com/quantumvisio/pixelstream",
    },
    {
        "title": "VivaWave AudioScope",
        "description": (
            "Perfect for live audio transcription, sentiment analysis, and "
            "emotion detection in speech streams."
        ),
        "provider": "Sonora Labs",
        "modality": "Voice",
        "price": "$0.10 / second",
        "latency_ms": 100,
        "use_case_tags": ["speech recognition", "sentiment", "emotion"],
        "source_url": "https://docs.sonoralabs.com/vivawave/audioscope",
    },
    {
        "title": "VividStream VisionSynth",
        "description": (
            "Enables dynamic video content generation and editing for "
            "creative media applications."
        ),
        "provider": "Pixsy Studios",
        "modality": "Video",
        "price": "$0.07 / second",
        "latency_ms": 80,
        "context_window": "10s max",
        "use_case_tags": ["video editing", "content creation", "animation"],
        "source_url": "https://docs.pixsystudios.com/vividstream/visionsynth",
    },
    {
        "title": "SkyPulse ImageFlow",
        "description": (
            "Specializes in real-time high-resolution image generation and "
            "enhancement for media production."
        ),
        "provider": "Skyline AI",
        "modality": "Image",
        "price": "$0.03 / image",
        "latency_ms": 30,
        "use_case_tags": ["image synthesis", "photo enhancement", "media creation"],
        "source_url": "https://docs.skylineai.com/sky.pulse/imageflow",
    },
    {
        "title": "NeuroVision Spectrum",
        "description": (
            "Specialized for high-fidelity image generation and enhancement "
            "tasks, ideal for creative design and media production."
        ),
        "provider": "Plexora AI Labs",
        "modality": "Image",
        "price": "$0.12 / image",
        "latency_ms": 250,
        "use_case_tags": ["creative", "design", "image enhancement"],
        "source_url": "https://docs.plexoraaibots.com/neurovision-spectrum",
    },
    {
        "title": "SynergyFlow Multimodal-X",
        "description": (
            "Designed for seamless integration of text, image, and audio "
            "inputs, perfect for complex multimedia projects."
        ),
        "provider": "VortexQ Solutions",
        "modality": "Multimodal",
        "price": "$0.25 / 1M tokens",
        "latency_ms": 400,
        "context_window": "80K",
        "use_case_tags": [
            "multimedia integration",
            "context understanding",
            "creative workflows",
        ],
        "source_url": "https://docs.vortexqsolutions.com/synergyflow-x",
    },
    {
        "title": "AstraMind Quantum",
        "description": (
            "A high-speed language model optimized for advanced reasoning "
            "and complex problem-solving tasks."
        ),
        "provider": "Celestial Computing",
        "modality": "LLM",
        "price": "$0.02 / 1K tokens",
        "latency_ms": 45,
        "context_window": "32K",
        "use_case_tags": ["reasoning", "analytics", "AI assistants"],
        "source_url": "https://docs.celestialcomputing.com/astramind-quantum",
    },
    {
        "title": "AuroraVibe VideoSynth",
        "description": (
            "Creates dynamic video content and animations from text "
            "prompts, suitable for media production."
        ),
        "provider": "NebulaMedia",
        "modality": "Video",
        "price": "$0.20 / second",
        "latency_ms": 500,
        "context_window": "10s max",
        "use_case_tags": ["video generation", "media", "animation"],
        "source_url": "https://docs.nebulamedia.com/auroravibe-videosynth",
    },
    {
        "title": "VoltStream ChatGPT-X",
        "description": (
            "Advanced conversational AI tailored for customer support and "
            "interactive dialogue systems."
        ),
        "provider": "QuantumCloud",
        "modality": "LLM",
        "price": "$0.015 / 1K tokens",
        "latency_ms": 30,
        "context_window": "16K",
        "use_case_tags": ["chatbots", "customer support", "dialogue"],
        "source_url": "https://docs.quantumcloud.com/voltstream-chatgpt-x",
    },
    {
        "title": "PhotonEmbed EmbeddingX",
        "description": (
            "Provides dense vector representations for text and images to "
            "improve search and recommendation systems."
        ),
        "provider": "FlickerTech",
        "modality": "Embedding",
        "price": "$0.005 / 1K embeddings",
        "use_case_tags": ["recommendation", "search", "semantic matching"],
        "source_url": "https://docs.flickertech.com/photonembed-embeddingx",
    },
    {
        "title": "NeuraVerse CortiFlow",
        "description": (
            "A multimodal platform enabling comprehensive contextual "
            "understanding for complex data analysis."
        ),
        "provider": "DataOrbit",
        "modality": "Multimodal",
        "price": "$0.28 / 1M tokens",
        "latency_ms": 420,
        "context_window": "90K",
        "use_case_tags": [
            "data analysis",
            "context recognition",
            "knowledge synthesis",
        ],
        "source_url": "https://docs.dataorbit.com/neuroverse-cortiflow",
    },
    {
        "title": "VentoVoice FX",
        "description": (
            "Enables expressive voice conversion and enhancement for "
            "entertainment and media production."
        ),
        "provider": "SonicWave Dynamics",
        "modality": "Voice",
        "price": "$0.09 / second",
        "latency_ms": 160,
        "use_case_tags": ["voice conversion", "speech editing", "audio effects"],
        "source_url": "https://docs.sonicwavedynamics.com/ventovox-fx",
    },
    {
        "title": "CrystaFrame Imagecraft",
        "description": (
            "High-resolution image rendering for detailed and "
            "photorealistic visual content creation."
        ),
        "provider": "OptiPix Studios",
        "modality": "Image",
        "price": "$0.11 / image",
        "latency_ms": 330,
        "use_case_tags": ["photorealism", "visual content", "rendering"],
        "source_url": "https://docs.optipixstudios.com/crystaframe-imagecraft",
    },
    {
        "title": "MetaNarrate TextStream",
        "description": (
            "Excellent for generating long-form narrative content, "
            "including stories and articles."
        ),
        "provider": "Luminant AI",
        "modality": "LLM",
        "price": "$0.018 / 1K tokens",
        "latency_ms": 35,
        "context_window": "24K",
        "use_case_tags": ["content creation", "storytelling", "writing assistance"],
        "source_url": "https://docs.luminantai.com/metanarrate-textstream",
    },
    {
        "title": "CelestiView Multimodal-A2",
        "description": (
            "Designed for comprehensive data analysis combining text, "
            "images, and video streams in real-time."
        ),
        "provider": "Skyline Dynamics",
        "modality": "Multimodal",
        "price": "$0.07 / input combo",
        "latency_ms": 200,
        "context_window": "16K",
        "use_case_tags": ["data fusion", "multimedia analysis", "real-time processing"],
        "source_url": "https://docs.skyline-dynamics.com/celestiview-a2",
    },
    {
        "title": "ArkadiaVision ImagePlus",
        "description": (
            "Optimized for high-resolution image recognition and detailed "
            "visual analysis tasks."
        ),
        "provider": "Arkadia Tech",
        "modality": "Image",
        "price": "$0.03 / image",
        "latency_ms": 80,
        "use_case_tags": ["visual recognition", "medical imaging", "Object detection"],
        "source_url": "https://docs.arkadia-tech.com/imageplus",
    },
    {
        "title": "SpectraFlow VideoSynth",
        "description": (
            "Great for generating and editing high-quality synthetic videos "
            "with contextual awareness."
        ),
        "provider": "NovaSynth Labs",
        "modality": "Video",
        "price": "$0.12 / second",
        "latency_ms": 250,
        "context_window": "10s max",
        "use_case_tags": ["video generation", "special effects", "content creation"],
        "source_url": "https://docs.novasynthlabs.com/spectraflow",
    },
    {
        "title": "HydraVision Augment",
        "description": (
            "Supports advanced visual augmentation for AR/VR applications "
            "with high fidelity."
        ),
        "provider": "Augmenta Labs",
        "modality": "Image",
        "price": "$0.05 / image",
        "latency_ms": 100,
        "use_case_tags": ["AR/VR", "visual augmentation", "immersive tech"],
        "source_url": "https://docs.augmenta.com/hydravision",
    },
    {
        "title": "VeraSight VisualSynth",
        "description": (
            "Specialized for high-fidelity image generation and editing "
            "tasks in creative workflows."
        ),
        "provider": "Lunaris Labs",
        "modality": "Image",
        "price": "$0.05 / image",
        "latency_ms": 300,
        "use_case_tags": ["art creation", "photo editing", "visual design"],
        "source_url": "https://docs.lunarislabs.com/verasight",
    },
    {
        "title": "OptiFlow Multimodal-X",
        "description": (
            "Integrates text, image, and video understanding for "
            "comprehensive multimedia analysis."
        ),
        "provider": "NovaTech AI",
        "modality": "Multimodal",
        "price": "$0.08 / 1M tokens",
        "latency_ms": 450,
        "context_window": "128K",
        "use_case_tags": [
            "multimedia analysis",
            "content moderation",
            "context understanding",
        ],
        "source_url": "https://docs.novatechai.com/optiflow",
    },
    {
        "title": "BioWave VoiceSynth",
        "description": (
            "Excellent for realistic speech synthesis and voice conversion "
            "applications."
        ),
        "provider": "AudioCore Dynamics",
        "modality": "Voice",
        "price": "$0.10 / second",
        "latency_ms": 50,
        "use_case_tags": ["text-to-speech", "voice cloning", "interactive voice"],
        "source_url": "https://docs.audiocoredynamics.com/biowave",
    },
    {
        "title": "DeepRender VideoPro",
        "description": (
            "Optimized for high-quality video generation with fast " "rendering times."
        ),
        "provider": "VisioSpark AI",
        "modality": "Video",
        "price": "$0.02 / second",
        "latency_ms": 200,
        "context_window": "10s max",
        "use_case_tags": ["video creation", "animation", "visual storytelling"],
        "source_url": "https://docs.visiosparkai.com/deeprender",
    },
    {
        "title": "NexaEmbed Embeddify",
        "description": (
            "Provides compact, semantic embeddings suitable for search and "
            "retrieval tasks."
        ),
        "provider": "CortexFoundry",
        "modality": "Embedding",
        "price": "$0.0002 / character",
        "latency_ms": 5,
        "use_case_tags": ["search", "recommendation", "semantic understanding"],
        "source_url": "https://docs.cortexfoundry.com/nexaembed",
    },
    {
        "title": "LumaImage RenderX",
        "description": (
            "Designed for rapid, high-resolution image rendering and "
            "enhancement in digital art projects."
        ),
        "provider": "PixelForge Labs",
        "modality": "Image",
        "price": "$0.07 / image",
        "latency_ms": 250,
        "use_case_tags": ["digital art", "image enhancement", "rendering"],
        "source_url": "https://docs.pixelforgelabs.com/lumaimagere",
    },
]


def main() -> None:
    settings = Settings()
    session_factory = build_session_factory(settings)
    vector_store = ModelVectorStore(
        settings.chroma_db_path,
        collection_name=settings.chroma_collection_name,
        embedding_function=build_embedding_function(settings),
    )
    admin_email = os.getenv("SEED_ADMIN_EMAIL", "curator@trailmind.dev").lower()
    admin_password = os.getenv("SEED_ADMIN_PASSWORD", "admin@123")
    engineer_email = os.getenv("SEED_ENGINEER_EMAIL", "engineer@trailmind.dev").lower()
    engineer_password = os.getenv("SEED_ENGINEER_PASSWORD", "engineer@123")

    with session_factory() as session:
        admin = session.scalar(select(User).where(User.email == admin_email))
        if not admin:
            session.add(
                User(
                    email=admin_email,
                    password_hash=hash_password(admin_password),
                    role="admin",
                )
            )
        else:
            admin.role = "admin"
            admin.password_hash = hash_password(admin_password)

        engineer = session.scalar(select(User).where(User.email == engineer_email))
        if not engineer:
            session.add(
                User(
                    email=engineer_email,
                    password_hash=hash_password(engineer_password),
                    role="user",
                )
            )
        else:
            engineer.role = "user"
            engineer.password_hash = hash_password(engineer_password)

        for values in SEED_MODELS:
            model = session.scalar(select(Model).where(Model.title == values["title"]))
            if not model:
                model = Model(**values, vector_synced=False)
                session.add(model)
                session.flush()
            else:
                for key, value in values.items():
                    setattr(model, key, value)
            vector_store.upsert(model)
            model.vector_synced = True
        session.commit()

    print(f"Seeded Curator account: {admin_email}")
    print(f"Seeded AI-engineer account: {engineer_email}")
    print(f"Seeded {len(SEED_MODELS)} models into SQL and Chroma")


if __name__ == "__main__":
    main()
