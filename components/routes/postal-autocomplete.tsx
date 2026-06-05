"use client";

import { useEffect, useRef, useState } from "react";
import { APIProvider, useMapsLibrary } from "@vis.gl/react-google-maps";
import { MapPin, Loader2, Search } from "lucide-react";
import { Input } from "@/components/ui/input";

/* ----------------------------------------------------------------------------
   Google Places autocomplete that resolves a searched address / neighbourhood
   to its POSTAL CODE. The manager searches a place to confirm exactly which
   postal code they're targeting; selecting fills the field with that code (the
   actual route generation still runs on the postal code). Falls back to a plain
   text field when no Maps key is set.
---------------------------------------------------------------------------- */

export interface PostalPlace {
  /** postal code if the place has one, else the place label */
  area: string;
  label: string;
  lat: number;
  lng: number;
  bounds?: { minLat: number; maxLat: number; minLng: number; maxLng: number };
}

interface Props {
  value: string;
  /** fired while typing (no resolved coordinates) */
  onChange: (text: string) => void;
  /** fired when a place is picked - carries real coordinates so generation does
   *  not have to re-geocode a bare postal code */
  onSelect?: (place: PostalPlace) => void;
  placeholder?: string;
}

export function PostalAutocomplete(props: Props) {
  const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
  if (!apiKey) {
    return (
      <Input
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        placeholder={props.placeholder}
        autoCapitalize="characters"
        className="uppercase placeholder:normal-case placeholder:text-faint"
      />
    );
  }
  return (
    <APIProvider apiKey={apiKey}>
      <Inner {...props} />
    </APIProvider>
  );
}

type Prediction = google.maps.places.AutocompletePrediction;

function Inner({ value, onChange, onSelect, placeholder }: Props) {
  const places = useMapsLibrary("places");
  const [query, setQuery] = useState(value);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);

  const svcRef = useRef<google.maps.places.AutocompleteService | null>(null);
  const detailsRef = useRef<google.maps.places.PlacesService | null>(null);
  const tokenRef = useRef<google.maps.places.AutocompleteSessionToken | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!places) return;
    svcRef.current = new places.AutocompleteService();
    detailsRef.current = new places.PlacesService(document.createElement("div"));
    tokenRef.current = new places.AutocompleteSessionToken();
  }, [places]);

  // close the dropdown on outside click
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const search = (text: string) => {
    if (!svcRef.current || text.trim().length < 2) {
      setPredictions([]);
      return;
    }
    setLoading(true);
    svcRef.current.getPlacePredictions(
      {
        input: text,
        sessionToken: tokenRef.current ?? undefined,
        componentRestrictions: { country: "ca" },
        types: ["geocode"],
      },
      (res) => {
        setLoading(false);
        setPredictions(res ?? []);
        setOpen(true);
      },
    );
  };

  const onType = (text: string) => {
    setQuery(text);
    setPicked(null);
    onChange(text); // typing a postal code directly still works
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(text), 220);
  };

  const choose = (p: Prediction) => {
    setOpen(false);
    setQuery(p.description);
    if (!detailsRef.current) return;
    detailsRef.current.getDetails(
      { placeId: p.place_id, fields: ["address_components", "formatted_address", "geometry"], sessionToken: tokenRef.current ?? undefined },
      (place, status) => {
        tokenRef.current = places ? new places.AutocompleteSessionToken() : null; // new session after a pick
        if (status !== google.maps.places.PlacesServiceStatus.OK || !place) return;
        const comp = place.address_components ?? [];
        const postal = comp.find((c) => c.types.includes("postal_code"))?.long_name;
        const label = postal ?? p.structured_formatting?.main_text ?? p.description;
        setQuery(label);
        setPicked(place.formatted_address ?? p.description);

        const loc = place.geometry?.location;
        const vp = place.geometry?.viewport;
        if (onSelect && loc) {
          const bounds = vp
            ? {
                minLat: vp.getSouthWest().lat(),
                maxLat: vp.getNorthEast().lat(),
                minLng: vp.getSouthWest().lng(),
                maxLng: vp.getNorthEast().lng(),
              }
            : undefined;
          onSelect({ area: label, label: place.formatted_address ?? p.description, lat: loc.lat(), lng: loc.lng(), bounds });
        } else {
          onChange(label);
        }
      },
    );
  };

  return (
    <div ref={boxRef} className="relative">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
        <Input
          value={query}
          onChange={(e) => onType(e.target.value)}
          onFocus={() => predictions.length && setOpen(true)}
          placeholder={placeholder}
          className="pl-9"
        />
        {loading && <Loader2 className="absolute right-3 top-1/2 size-4 -translate-y-1/2 animate-spin text-faint" />}
      </div>

      {open && predictions.length > 0 && (
        <div className="absolute z-50 mt-1.5 w-full overflow-hidden rounded-2xl border border-line bg-surface shadow-lift">
          {predictions.slice(0, 6).map((p) => (
            <button
              key={p.place_id}
              type="button"
              onClick={() => choose(p)}
              className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-surface-muted"
            >
              <MapPin className="mt-0.5 size-4 shrink-0 text-primary-500" />
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-medium text-ink">
                  {p.structured_formatting?.main_text ?? p.description}
                </span>
                <span className="block truncate text-[11px] text-muted">
                  {p.structured_formatting?.secondary_text ?? ""}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}

      {picked && (
        <p className="mt-1.5 flex items-center gap-1 text-[11px] font-medium text-primary-700">
          <MapPin className="size-3" /> {picked}
        </p>
      )}
    </div>
  );
}
