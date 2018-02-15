#
# HashPype class which uses ObsPy Event as I/O for focal mech data
# 
from hashpy.doublecouple import DoubleCouple
from obspy.core.utcdatetime import UTCDateTime
from obspy.core.event import (Catalog, Event, Origin, CreationInfo, Magnitude,
    EventDescription, OriginUncertainty, OriginQuality, CompositeTime,
    ConfidenceEllipsoid, StationMagnitude, Comment, WaveformStreamID, Pick,
    QuantityError, Arrival, FocalMechanism, MomentTensor, NodalPlanes,
    PrincipalAxes, Axis, NodalPlane, SourceTimeFunction, Tensor, DataUsed,
    ResourceIdentifier, StationMagnitudeContribution)

PREFIX = "smi:local.hashserver"

#TODO:rm - Quick fix for version compat - MCW
if hasattr(ResourceIdentifier, "get_referred_object"):
    ResourceIdentifier.getReferredObject = ResourceIdentifier.get_referred_object

def _get_pick(arrival, picks, pick_ids):
    """
    Return the associated pick of an arrival, even if not set as referred object
    """
    pid = arrival.pick_id
    pick = pid.getReferredObject()
    if pick is None:
        try:
            n = pick_ids.index(pid)
        except:
            return pick
        else:
            return picks[n]
    return pick


def rid(resource_id, prefix=""):
    if prefix is not None:
        p = prefix or PREFIX
        resource_id = "/".join([p, resource_id])
    return ResourceIdentifier(resource_id)


def input_event(hp, event):
    """
    Load Event into HASH
    
    Takes origin, arrival, pick information from an Event and loads
    up the HASH arrays needed for the focal mechanism calculation.
    
    Input
    -----
    event : obspy.core.event.Event instance
    
      ** event.preferred_origin_id should be set to the origin in
         event.origins you want to use
    """
    DEFAULT_UNCERT = 1000.
    
    # Takes an obspy event and loads FM data into HASH
    _o = event.preferred_origin()
    _m = event.preferred_magnitude()
    _pids = [p.resource_id for p in event.picks]
    _uncert = _o.origin_uncertainty

    hp.tstamp = _o.time.timestamp
    hp.qlat   = _o.latitude
    hp.qlon   = _o.longitude
    hp.qdep   = _o.depth / 1000.
    hp.icusp  = _o.creation_info.version
    
    # Try to get valid hoizontal/vertical errors.
    if _uncert.horizontal_uncertainty:
        hp.seh = _uncert.horizontal_uncertainty or DEFAULT_UNCERT
    elif _uncert.confidence_ellipsoid:
        hp.seh = _uncert.confidence_ellipsoid.semi_major_axis_length or DEFAULT_UNCERT
    else:
        hp.seh = DEFAULT_UNCERT
    
    hp.seh /= 1000.
    hp.sez = _o.depth_errors.get('uncertainty', DEFAULT_UNCERT) / 1000.

    if _m:
	    hp.qmag = _m.mag
    
    # The index 'k' is deliberately non-Pythonic to deal with the fortran
    # subroutines which need to be called and the structure of the original HASH code.
    # May be able to update with a rewrite... YMMV
    hp.p_index = []
    k = 0
    for _i, arrv in enumerate(_o.arrivals):
        hp.logger.debug("Got arrival: {}".format(_i))

        pick = _get_pick(arrv, event.picks, _pids)
        if pick is None:
            hp.logger.debug("Couldn't find pick for: {}".format(_i))
            continue

        hp.sname[k] = pick.waveform_id.station_code
        hp.snet[k]  = pick.waveform_id.network_code
        hp.scomp[k] = pick.waveform_id.channel_code
        hp.arid[k]  = pick.creation_info.version
        
        hp.qazi[k] = arrv.azimuth
        hp.dist[k] = arrv.distance * 111.2
        
        if (hp.qazi[k] < 0.):
            hp.qazi[k] += 360.
        
        if (hp.dist[k] > hp.delmax):
            hp.logger.debug("Pick failed delta: {}".format(_i))
            continue
            
        if arrv.phase not in 'Pp':
            hp.logger.debug("Pick not P phase: {}".format(_i))
            continue
        
        if (pick.polarity == 'positive'):
            hp.p_pol[k] = 1
        elif (pick.polarity == 'negative'):
            hp.p_pol[k] = -1
        else:
            hp.logger.debug("Pick not pos/neg: {}".format(_i))
            continue
        
        if  (pick.onset == 'impulsive'):
            hp.p_qual[k] = 0
        elif (pick.onset == 'emergent'):
            hp.p_qual[k] = 1
        elif (pick.onset == 'questionable'):
            hp.p_qual[k] = 1
        else:
            hp.p_qual[k] = 0
            
        # polarity check in original code... doesn't work here
        #hp.p_pol[k] = hp.p_pol[k] * hp.spol
        hp.p_index.append(_i) # indicies of [arrivals] which passed
        k += 1
    hp.npol = k # k is zero indexed in THIS loop


def output_event(hp, event=None, only_fm_picks=False):
    """
    Make an Event which includes the current focal mechanism information from HASH
    
    Use the 'only_fm_picks' flag to only include the picks HASH used for the FocalMechanism.
    This flag will replace the 'picks' and 'arrivals' lists of existing events with new ones.
    
    Inputs
    -------
    hp    : hashpy.HashPype instance
    
    event : obspy.core.event.Event
    
    only_fm_picks : bool of whether to overwrite the picks/arrivals lists
    
    
    Returns
    -------
    obspy.core.event.Event
    
    Event will be new if no event was input, FocalMech added to existing event
    """
    # Returns new (or updates existing) Event with HASH solution
    n = hp.npol
    if event is None:
        event = Event(focal_mechanisms=[], picks=[], origins=[])
        origin = Origin(arrivals=[])
        origin.time = UTCDateTime(hp.tstamp)
        origin.latitude = hp.qlat
        origin.longitude = hp.qlon
        origin.depth = hp.qdep * 1000.
        origin.creation_info = CreationInfo(version=hp.icusp)
        origin.resource_id = rid('Origin/{0}'.format(hp.icusp))
        for _i in range(n):
            p = Pick()
            p.creation_info = CreationInfo(version=hp.arid[_i])
            p.resource_id = rid('Pick/{0}'.format(p.creation_info.version))
            p.waveform_id = WaveformStreamID(network_code=hp.snet[_i], station_code=hp.sname[_i], channel_code=hp.scomp[_i])
            if hp.p_pol[_i] > 0:
                p.polarity = 'positive'
            else:
                p.polarity = 'negative'
            a = Arrival()
            a.creation_info = CreationInfo(version=hp.arid[_i])
            a.resource_id = rid('Arrival/{0}'.format(p.creation_info.version))
            a.azimuth = hp.p_azi_mc[_i,0]
            a.takeoff_angle = 180. - hp.p_the_mc[_i,0]
            a.pick_id = p.resource_id
            origin.arrivals.append(a)
            event.picks.append(p)
        event.origins.append(origin)
        event.preferred_origin_id = str(origin.resource_id)
    else: # just update the changes
        origin = event.preferred_origin()
        picks = []
        arrivals = []
        for _i in range(n):
            ind = hp.p_index[_i]
            a = origin.arrivals[ind]
            p = a.pick_id.getReferredObject()
            a.takeoff_angle = 180. - hp.p_the_mc[_i,0]
            picks.append(p)
            arrivals.append(a)
        if only_fm_picks:
            origin.arrivals = arrivals
            event.picks = picks
    # Use me double couple calculator and populate planes/axes etc
    x = hp._best_quality_index
    # Put all the mechanisms into the 'focal_mechanisms' list, mark "best" as preferred
    for s in range(hp.nmult):
        dc = DoubleCouple([hp.str_avg[s], hp.dip_avg[s], hp.rak_avg[s]])
        ax = dc.axis
        fmid = 'FocalMechanism/{0}-{1}'.format(hp.icusp, s+1)
        cmts = [
            Comment(
                text = hp.settings_str,
                resource_id = rid(fmid+"#hash-settings"),
            ),
            Comment(
                text = str(hp.qual[s]),
                resource_id = rid(fmid+"#hash-qual"),
            ),
        ]
        focal_mech = FocalMechanism()
        focal_mech.creation_info = CreationInfo(creation_time=UTCDateTime(), author=hp.author)
        focal_mech.triggering_origin_id = origin.resource_id
        focal_mech.resource_id = rid(fmid)
        focal_mech.method_id = rid('Method/HASH')
        focal_mech.nodal_planes = NodalPlanes()
        focal_mech.nodal_planes.nodal_plane_1 = NodalPlane(*dc.plane1)
        focal_mech.nodal_planes.nodal_plane_2 = NodalPlane(*dc.plane2)
        focal_mech.principal_axes = PrincipalAxes()
        focal_mech.principal_axes.t_axis = Axis(azimuth=ax['T']['azimuth'], plunge=ax['T']['dip'])
        focal_mech.principal_axes.p_axis = Axis(azimuth=ax['P']['azimuth'], plunge=ax['P']['dip'])
        focal_mech.station_polarity_count = n
        focal_mech.azimuthal_gap = hp.magap
        focal_mech.misfit = hp.mfrac[s]
        focal_mech.station_distribution_ratio = hp.stdr[s]
        focal_mech.comments += cmts
        #----------------------------------------
        event.focal_mechanisms.append(focal_mech)
        if s == x:
            event.preferred_focal_mechanism_id = str(focal_mech.resource_id)
    return event
    